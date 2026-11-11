# 招聘市场数据实时分析

把公开招聘信息采集下来、做标准化治理，再用看板回答「某个城市 / 方向的岗位多不多、
给多少钱、要什么技能」。当前版本 **v0.1.0（内部）**。

全链路已跑通：数据源（mohrss A 级 + BOSS B 级）→ 原始层落盘 → 解析 → 标准化 →
PostgreSQL → 指标视图 → 控制台 API → 可视化看板（7 模块 + 8 图表 + 状态栏）。

> ### ⚠️ 合规声明（请先读这一段）
>
> - 本仓库**只公开代码**，不含任何采集到的数据、原始页或日志；`data/`、`logs/`、
>   `reference/` 均被 `.gitignore` 排除。README 里的截图全部由**合成演示数据**生成。
> - 采集代码仅用于**学习与技术演示**。使用者须自行确保遵守目标站点的 `robots.txt`
>   与服务条款，以及《数据安全法》《个人信息保护法》《反不正当竞争法》等法律法规；
>   **作者不提供、不托管、不分发任何数据**。
> - 代码按设计**不接收、不存储**招聘方个人联系方式（HR 姓名 / 电话 / 邮箱 / 微信），
>   原始层落盘前即脱敏（见 `jobmvp/pii.py`）。
> - 使用本代码产生的数据合法性、账号风控与法律责任由使用者自行承担。
>   十条硬约束的代码落点见 [合规与边界](docs/合规与边界.md)，安全问题走 [SECURITY.md](SECURITY.md)。

---

![看板概览](docs/images/dashboard.png)

<details>
<summary>展开看另外三页：市场结构 / 技能需求 / 薪资分析</summary>

![市场结构](docs/images/market.png)

![技能需求](docs/images/skills.png)

![薪资分析](docs/images/salary.png)

</details>

> 截图由 `tools/demo_seed.py` 灌入的合成数据生成（公司名带「示例」、岗位标题带「（示例）」、
> 链接指向 `example.invalid`），可直接复现，不涉及任何真实抓取内容。

## 解决什么问题

| 痛点 | 本项目的做法 |
|---|---|
| 招聘网站薪资是字体加密乱码，抓下来没法用 | 走接口层拿明文 `salaryDesc`（DOM 是 `-K` 乱码，API 是 `10-11K`） |
| 同一个岗位被反复发布，统计数据虚高 | 业务键去重（`m_job_dedup`），每组保留最新 |
| 不同源的城市写法不一致（省/市/区混用） | 区划码优先 + 城市/区县拆分 |
| 薪资写「面议」或只有单边（`3000元以上`） | 双边界 / 仅下限 / 仅上限三态解析，标记 `salary_ok` |
| 想找工作但岗位太多看不过来 | 求职意向打分（城市 25 + 薪资 30 + 技能 35 + 岗类 10） |
| 采集出问题不知道哪一步坏了 | 每步写日志（关键词 × 城市 × 页的 code / 条数 / 耗时 / 异常）+ 状态栏监控 |

## 核心能力

**采集** — 多源适配器（mohrss A 级、BOSS B 级）；BOSS 三种模式 `http` / `browser` /
**`cdp` 旁听**（15 条/页）/ 主动调接口（30 条/页）；合规闸门：未启用源不发请求、
B 级需审批、PII 硬拦截、遇验证码即停。

**治理** — 薪资三态解析与单位统一（元/千/万 → 月薪 K）；技能词表按单词边界匹配
（避免 `Java` 命中 `JavaScript`）；岗类映射 + 未映射队列；生命周期状态机
`active → missing n 次 → closed`，覆盖率达标记才判下架。

**分析** — 岗类分布、城市分布、业务领域、技能热度 Top15、技能 × 岗类热力矩阵、
薪资分位（P25/P50/P75）、薪资分布直方图、经验要求分布。

**运营** — 采集配置（关键词 + 城市 + 页数 + 间隔，内置调度器读此执行）、求职意向与
岗位匹配度、采集日志（支持只看异常）、底部状态栏（10 秒刷新）。

## 技术栈与架构

| 层 | 选型 |
|---|---|
| 语言 | Python ≥ 3.10 |
| 数据库 | PostgreSQL（业务库 `jobmvp` / 测试库 `jobmvp_test`） |
| 采集 | httpx + lxml（mohrss）、Playwright + CDP（BOSS） |
| 后端 | FastAPI + uvicorn |
| 前端 | 单文件 HTML + 内联 CSS/JS（无构建、无框架依赖） |
| 测试 | pytest（111 个用例，跑真实 PostgreSQL） |
| 调度 | 服务进程内调度器（读 `scrape_plan.interval_minutes`，默认 60 分钟） |

```
数据源 ──► SourceAdapter（discover / fetch / parse）
              │  合规闸门：enabled? 审批? robots? 验证码?
              ▼
        原始层（data/raw/source/日期，可重放）
              │  解析 + PII 脱敏
              ▼
        标准化（normalize.py：薪资 / 经验 / 地区 / 技能 / 岗类）
              ▼
        PostgreSQL ──► job（明细）+ m_*（指标视图）
              │
              ├──► FastAPI（20+ 接口）──► 看板（7 模块 + 8 图表 + 状态栏）
              └──► 内置调度器（按计划定时采集）
```

## 快速开始

需要 Python ≥ 3.10、PostgreSQL ≥ 14（开发机实测 18.4）。

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt

# 建库 + 建表 + 指标视图（详见使用指南）
.venv/Scripts/python.exe -m tools.seed_dicts --with-regions

# 配置外置：连接串写进 .env（已被 .gitignore 忽略）
#   JOBMVP_DSN=postgresql://mvp:<口令>@127.0.0.1:5432/jobmvp
#   TEST_DSN=postgresql://mvp:<口令>@127.0.0.1:5432/jobmvp_test

# 起服务 → 打开 http://127.0.0.1:8010/ui?key=devkey
.venv/Scripts/python.exe -m uvicorn console.app:app --host 127.0.0.1 --port 8010
```

接口需带 `X-API-Key`；未配置 `JOBMVP_API_KEY` 时一律 401。完整步骤（建库脚本、
采集入口、测试、重置数据库、常见坑）见 **[使用指南](docs/使用指南.md)**。

## 目录结构

```
EmploymentAnalysis/
├── jobmvp/
│   ├── adapter.py        适配器基类 + robots + 验证码检测 + 字段白名单
│   ├── pii.py            原始层落盘前的 PII 脱敏（联系人 / 电话 / 邮箱）
│   ├── normalize.py      薪资 / 经验 / 地区 / 技能 / 岗类（纯函数，可单测）
│   ├── runner.py         单源编排（闸门 → 抓 → 落盘 → 解析 → 标准化 → 入库 → 下架）
│   ├── store.py          入库、生命周期、审计、僵尸运行回收
│   ├── boss_collect.py   BOSS 采集核心（CDP + 接口，带进度回调）
│   ├── scheduler.py      内置调度器（按 interval_minutes 判到期）
│   ├── env.py            .env 加载（已存在的环境变量优先）
│   └── sources/          各站适配器（mohrss.py …）
├── console/app.py        FastAPI 后端（20+ 接口）
├── console/ui.py         看板前端（单文件）
├── sql/                  表结构 / 指标与去重视图 / 采集配置 / 求职意向
├── tools/                播种、区划生成、采集 CLI、演示数据、凭据扫描
├── tests/                111 个用例（需真实 PG）
├── docs/                 使用者文档 + 看板截图（开发过程文档不入库）
└── data/raw/             原始层：按 source/日期 落盘，可重放（不入库）
```

## 文档

| 文档 | 内容 |
|---|---|
| [使用指南](docs/使用指南.md) | 环境、建库、配置、采集、看板、测试、重置数据库 |
| [采集与数据源](docs/采集与数据源.md) | 两个源的口径、BOSS 三道门与三种模式、外部导入、调度 |
| [看板与接口](docs/看板与接口.md) | 接口清单、7 个看板模块、采集日志与运行日志 |
| [指标口径](docs/指标口径.md) | 指标视图定义、业务去重、薪资解析、分位数怎么读 |
| [合规与边界](docs/合规与边界.md) | 十条不可绕过的硬约束及其代码落点 |
| [实测结果](docs/实测结果.md) | 真实采集跑出来的数字与已知偏差 |
| [SECURITY.md](SECURITY.md) | 漏洞报告渠道、设计边界、使用者责任 |

## 许可

Apache License 2.0，见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。允许商用、修改、再分发；
分发修改版需保留原许可声明并标注改动。含专利授权（第 3 条）与免责条款（第 7、8 条），
不授予商标使用权（第 6 条）。

提交前自检凭据：`.venv/Scripts/python.exe tools/scan_secrets.py`（工作区 + 全历史，命中退出码 1）。
