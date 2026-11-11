# 招聘市场数据实时分析

按 `docs/招聘市场实时数据分析与可视化产品方案.md` 与 `reference/jobmvp-参考实现/` 的约束实现，
当前版本 **v0.1.0（内部）**。

**当前状态**：全链路已跑通 —— 真实数据源（mohrss A 级 + BOSS B 级）→ 原始层落盘 → 解析 → 标准化
→ PostgreSQL → 指标视图 → 控制台 API → 可视化看板（5 模块 + 8 图表 + 底部状态栏）。

**已具备**：多源采集（含 BOSS CDP 旁听 / 主动调 API）、业务去重、薪资分位、技能热度、业务领域、
经验分布、岗位匹配度（求职意向）、采集配置、实时状态监控、**内置采集调度器**（点按钮采集 / 按间隔自动采集）。

> ### ⚠️ 合规声明（请先读这一段）
>
> - 本仓库**只公开代码**，不包含任何采集到的数据、原始页或日志；`data/`、`logs/`、`reference/` 均被 `.gitignore` 排除。
>   README 里唯一一张看板截图是用**合成演示数据**拍的，不含真实岗位、公司或个人信息。
> - 采集代码仅用于**学习与技术演示**。使用者须自行确保遵守目标站点的 `robots.txt`、服务条款，
>   以及《数据安全法》《个人信息保护法》《反不正当竞争法》等法律法规；**作者不提供、不托管、不分发任何数据**。
> - 代码按设计**不接收、不存储**招聘方个人联系方式（HR 姓名 / 电话 / 邮箱 / 微信），原始层落盘前即脱敏（见 `jobmvp/pii.py`）。
> - 任何因使用本代码产生的数据合法性、账号风控、法律责任由使用者自行承担。详见 [`SECURITY.md`](SECURITY.md)。

---

![看板概览](docs/images/dashboard.png)

> 看板概览页：KPI、数据质量、数据源合规闸门、新发岗位趋势。**截图为演示数据，全部虚构** ——
> 公司名统一带"示例"字样，岗位与薪资是合成分布，不含任何真实岗位、公司或个人信息。

<details>
<summary>展开看另外三页：市场结构 / 技能需求 / 薪资分析</summary>

![市场结构](docs/images/market.png)

![技能需求](docs/images/skills.png)

![薪资分析](docs/images/salary.png)

</details>

> 以上截图全部由 `tools/demo_seed.py` 灌入的合成数据生成（公司名带"示例"、岗位标题带"（示例）"、
> 链接指向 `example.invalid`），可直接复现，不涉及任何真实抓取内容。

## 0. 项目简介

### 这是什么

一个**个人向的招聘市场数据分析工具**：把公开招聘信息采集下来，做标准化与治理，
再用看板回答"某个城市/方向的岗位多不多、给多少钱、要什么技能"。

### 解决什么问题

| 痛点 | 本项目的做法 |
|---|---|
| 招聘网站薪资是字体加密乱码，抓下来没法用 | 走接口层拿明文 `salaryDesc`（DOM 是 `-K` 乱码，API 是 `10-11K`） |
| 同一个岗位被反复发布，统计数据虚高 | 业务键去重（`m_job_dedup`），每组保留最新 |
| 不同源的城市写法不一致（省/市/区混用） | 区划码优先 + 城市/区县拆分 |
| 薪资写"面议"或只有单边（`3000元以上`） | 双边界/仅下限/仅上限三态解析，标记 `salary_ok` |
| 想找工作但岗位太多看不过来 | 求职意向打分（城市25 + 薪资30 + 技能35 + 岗类10） |
| 采集出问题不知道哪一步坏了 | 每步写日志（关键词×城市×页的 code/条数/耗时/异常）+ 状态栏实时监控 |

### 核心能力

**采集**
- 多源适配器：`mohrss`（中国公共招聘网，A 级）、`boss`（BOSS 直聘，B 级）
- BOSS 三种模式：`http`（被拦）/ `browser`（被拦）/ **`cdp`（旁听，15 条/页）**
- 主动调 API：`page.request` 复用 cookie，**30 条/页**，支持多页 + 随机延迟
- 合规闸门：未启用源不发请求、B 级需审批、PII 硬拦截、验证码即停

**治理**
- 薪资三态解析 + 单位统一（元/千/万 → 月薪 K）
- 技能词表（单词边界，避免 `Java` 命中 `JavaScript`）
- 岗类映射 + 未映射队列（供人工补词表）
- 生命周期状态机：`active → missing_n 次 → closed`，覆盖率达标记才判下架

**分析（8 个可视化）**
- 岗类分布、城市分布、业务领域、技能热度 Top15
- 技能 × 岗类热力矩阵
- 薪资分位（P25/P50/P75）、薪资分布直方图、经验要求分布

**运营**
- 采集配置（关键词 + 城市 + 页数 + 自动采集间隔，项目内置调度器读此执行）
- 求职意向（期望城市/薪资/技能/岗类 → 岗位匹配度）
- 采集日志（每步 code/条数/耗时/异常，支持只看异常）
- 底部状态栏（监控/采集时间/运行时长/网络/账号/数据源，10 秒刷新）

### 技术栈

| 层 | 选型 |
|---|---|
| 语言 | Python 3.11 |
| 数据库 | PostgreSQL 18（业务库 `jobmvp` / 测试库 `jobmvp_test`） |
| 采集 | httpx + lxml（mohrss）、Playwright + CDP（BOSS） |
| 后端 | FastAPI + uvicorn |
| 前端 | 单文件 HTML + 内联 CSS/JS（无构建、无框架依赖） |
| 测试 | pytest（71 个用例，跑真实 PostgreSQL） |
| 调度 | **服务进程内调度器**（读 `scrape_plan.interval_minutes`，默认 60 分钟） |

### 数据规模（当前实测）

| 指标 | 值 |
|---|---|
| 明细记录 | 1,434 条 |
| 去重后在招 | 1,285 条 |
| 数据源 | 2 个（mohrss 384 + BOSS 1,050） |
| 覆盖城市 | 西安 / 北京 / 重庆 / 成都 / 台州 / 昆明 / 苏州 等 |
| 薪资可解析率 | 100% |
| 岗类映射率 | 89%+ |

### 架构

```
数据源 ──► SourceAdapter（discover/fetch/parse）
              │  合规闸门：enabled? 审批? robots? 验证码?
              ▼
        原始层（data/raw/source/日期，可重放）
              │  解析 + PII 白名单裁剪
              ▼
        标准化（normalize.py：薪资/经验/地区/技能/岗类）
              │
              ▼
        PostgreSQL ──► job（明细） + m_*（指标视图）
              │
              ├──► FastAPI（20+ 接口）
              │        │
              │        ▼
              └──► 看板（侧边栏 7 模块 + 8 图表 + 状态栏）
```

---

## 1. 环境

| 项 | 版本 | 说明 |
|---|---|---|
| Python | ≥ 3.10 | 代码使用 `X \| None`、`tuple[...]` |
| PostgreSQL | ≥ 14 | 本机实测 **18.4**（`D:\Tools\DBSoft\PostgreSQL`，端口 5432） |
| 依赖 | `requirements.txt` | psycopg 3.3.6 / fastapi 0.162.0 / httpx 0.28.1 / pytest 9.2.0 |

本机已创建：
- 角色 `mvp`（密码 `mvp`，CREATEDB）
- 业务库 `jobmvp`、测试库 `jobmvp_test`（均以 `template0` 为模板）

> 本机 `psql` 客户端缺失（安装包里没有），所有操作走 Python/psycopg 或 `pg_dump` 等工具。
> 若需 psql，可从同一安装包的 `bin` 补齐或另装客户端。

---

## 2. 快速开始

```bash
# 0) 虚拟环境（已建好，重建时用）
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt

# 1) 建库 + 建表 + 指标视图
#    （已执行过可跳过；重建见下方「重置数据库」）
.venv/Scripts/python.exe - <<'PY'
import pathlib, psycopg
sql = "".join(pathlib.Path(f"sql/{f}").read_text(encoding="utf-8")
              for f in ("001_schema.sql", "002_metrics.sql"))
for db in ("jobmvp", "jobmvp_test"):
    with psycopg.connect(f"postgresql://mvp:mvp@127.0.0.1:5432/{db}", autocommit=True) as c:
        c.execute(sql)
PY

# 2) 播种字典与源配置（幂等）
.venv/Scripts/python.exe -m tools.seed_dicts --with-regions

# 3) 启用数据源（合规闸门：默认关闭，必须显式启用）
.venv/Scripts/python.exe - <<'PY'
import psycopg
with psycopg.connect("postgresql://mvp:mvp@127.0.0.1:5432/jobmvp", autocommit=True) as c:
    c.execute("UPDATE source_config SET enabled=true, max_pages=20 WHERE source_id='mohrss'")
PY

# 4) 采集（20 页 ≈ 400 条，约 60~90 秒）
JOBMVP_DSN=postgresql://mvp:mvp@127.0.0.1:5432/jobmvp \
  .venv/Scripts/python.exe -m jobmvp.cli run mohrss --trigger manual

# 5) 控制台 API
JOBMVP_DSN=postgresql://mvp:mvp@127.0.0.1:5432/jobmvp JOBMVP_API_KEY=devkey \
  .venv/Scripts/python.exe -m uvicorn console.app:app --host 127.0.0.1 --port 8010
```

打开 **http://127.0.0.1:8010/ui?key=devkey** 即可视化首页（KPI / 数据质量 / 趋势 /
岗类与城市分布 / 薪资分位 / 运行历史 / 未映射队列 / 审计日志，右上角可一键触发采集）。
页面本身不含数据，所有数据都通过带 `X-API-Key` 的接口取。

> **配置外置（推荐）**：上面那些 `JOBMVP_DSN` 不必每次手打。把连接串写进仓库根目录的
> `.env`（已被 `.gitignore` 忽略，不会入库），`jobmvp` CLI、`console`、
> `scripts/dashboard_manager.py` 和 pytest 启动时都会自动读取（见 `jobmvp/env.py`）：
>
> ```ini
> JOBMVP_DSN=postgresql://mvp:<口令>@127.0.0.1:5432/jobmvp
> TEST_DSN=postgresql://mvp:<口令>@127.0.0.1:5432/jobmvp_test
> ```
>
> **已存在的环境变量优先**，`.env` 只填补空缺，方便临时覆盖。注意 pytest 会把
> `JOBMVP_DSN` 强制改指测试库（`tests/conftest.py`），防止跑测试把业务数据清空。

控制台接口（均需 `X-API-Key`，未配置 `JOBMVP_API_KEY` 时一律 401）：

| 接口 | 用途 |
|---|---|
| `GET /api/sources` | 源列表 + 最近一次运行 |
| `POST /api/sources/{id}/enable` | 启停源（B 级必须带 `approval_note`） |
| `POST /api/sources/{id}/run` | 触发运行（202，后台执行） |
| `GET /api/sources/{id}/runs` | 运行历史 |
| `GET /api/runs/{run_id}/errors` | 解析失败样本 |
| `GET /api/quality` | 数据质量面板 |
| `GET /api/jobs` | 岗位明细（`category` / `city` / `q` 过滤，`sort=posted\|salary_desc\|salary_asc` 排序 + 分页）；**已业务去重**，含源站详情链接 |
| `GET /api/unmapped` | 未映射岗位名队列（供人工归类） |
| `GET /api/metrics/{name}` | 指标视图（白名单） |
| `GET /api/audit` | 审计日志 |

> **僵尸运行**：服务被强杀会留下 `status='running'` 的记录，并因
> `one_running_per_source` 唯一索引阻塞该源后续运行。执行
> `python -m jobmvp.cli reap` 回收（默认只回收 6 小时前的；
> 调试时可 `store.reap_stale_runs(conn, 0)`）。

---

## 3. 目录结构

```
EmploymentAnalysis/
├── jobmvp/
│   ├── adapter.py        适配器基类 + robots + 验证码检测 + 白名单裁剪
│   ├── normalize.py      薪资/经验/地区/技能/岗类（纯函数，可单测）
│   ├── runner.py         单源运行编排（闸门→抓→落盘→解析→标准化→入库→下架）
│   ├── store.py          入库、生命周期、审计、僵尸运行回收
│   ├── registry.py       source_id → 适配器工厂
│   ├── taxonomy.py       出厂词表（岗类规则 / 技能别名）
│   ├── data/regions.json 区划码前4位 → 地级市（tools/gen_regions.py 生成）
│   ├── cli.py            run / reap（cron 入口）
│   └── sources/
│       └── mohrss.py     中国公共招聘网适配器（A 级）
├── console/app.py        FastAPI 后端（20+ 接口：岗位/指标/分析/配置/状态）
├── console/ui.py         看板前端（侧边栏 5 模块 + 8 图表 + 底部状态栏）
├── sql/                  001 表结构 / 002-004 指标与去重 / 005 采集配置 / 006 求职意向
├── tools/seed_dicts.py   字典与源配置播种
├── tools/gen_regions.py  生成行政区划映射表（源站 aa12.json）
├── jobmvp/boss_collect.py     BOSS 采集核心（CDP + joblist API，带进度回调）
├── jobmvp/scheduler.py        内置调度器（按 interval_minutes 判到期，服务进程内跑）
├── tools/boss_api_scrape.py   BOSS 采集 CLI 薄壳（参数解析 + 退出码，核心在 boss_collect）
├── tools/capture_boss_current.py  采集当前页面（仅页面导航模式兜底；API 模式可直接传 --city）
├── tools/boss_cdp_smoke.py    CDP 连通性自检
├── tools/start_boss_chrome.bat  启动 BOSS 专用 Chrome（9223 + 独立 profile）
├── tests/                71 个用例（需真实 PG）
├── data/raw/             原始层：按 source/日期 落盘，可重放
├── docs/                 产品方案、参考项目调研、架构笔记
└── reference/            三套参考工程（不入库）
```

---

## 4. 数据源

| source_id | 名称 | 等级 | 状态 | 说明 |
|---|---|---|---|---|
| `mohrss` | 中国公共招聘网 | **A** | 已接入，运行中 | 人社部公共就业平台公开列表页；无登录、无验证码；约 17 万条岗位；**默认按技术关键词轮转采集** |
| `boss` | BOSS直聘 | **B** | 已接入，**默认关闭** | 代码与解析器就位，但受 robots 与风控限制，当前拿不到数据（见下） |

采集口径：
- 只读列表页，**不进详情页**；单页 20 条；`min_interval_s=2`。
- 薪资：`acb241/acb242` 合成 `"8000-12000元/月"` 交给 `normalize.parse_salary`，落库为**千元/月**。
- 地区：只用 `aab302`（工作地）+ `aab301`（区划码），**不用 `acb202`** ——
  后者是单位注册地址，实测常与工作地不符（标"西安市"、地址在湖北武汉）。
  区县级岗位用同页学到的「区划码前 4 位 → 城市」归并。
- PII：源站列表含 `aae004`（联系人）/`aae005`（电话）/`aae013`（邮箱），
  适配器**根本不读取**这些键，加上 `sanitize()` 的 `PII_FIELDS` 双保险。

### 4.0 技术岗切口（默认策略）

产品首个垂直切口是「计算机 / IT 开发岗」，而该站全站顺序里技术岗只占 2~3%。
适配器默认按一组技术检索词**轮转**抓取（`discover()` 里 `i % len(keywords)`），
一次运行覆盖 12 个方向，技术岗占比提升到约 50%：

```python
DEFAULT_MOHRSS_KEYWORDS = [
    "Java", "Python", "前端", "后端", "测试", "运维",
    "算法", "网络", "系统", "软件工程师", "数据开发", "嵌入式",
]
```

- **城市优先**：默认 `DEFAULT_CITIES = [("610100","西安"), ("510100","成都")]`，
  `discover()` 先排「城市 × 关键词 × 页」，剩余配额才补全国；
  可用 `MOHRSS_CITIES="610100:西安,510100:成都"` 覆盖，设空串则只抓全国；
- 覆盖方式：`MOHRSS_KEYWORDS="Java,Go"`（逗号分隔）或 `jobmvp/registry.py` 里改默认值；
- 检索词匹配的是**岗位描述**，相关性有限，仍需靠岗类字典二次归类；
- 注意 `discover()` 必须走 `urlencode` —— 中文关键词不编码会被服务端忽略，返回一堆无关岗位（曾踩过）。

### 4.1 BOSS 直聘（B 级）现状

已实现 `jobmvp/sources/boss.py`，但**当前无法产出数据**，三道门依次关闭：

| 关卡 | 实测结果 |
|---|---|
| `source_config.enabled` | 默认 false，未启用时 `SourceDisabled`，一个请求都不发 |
| 库级 CHECK | `tier='B'` 且 `enabled=true` 时必须有 `approval_note`，否则 `CheckViolation` |
| robots.txt | **明确 `Disallow: /*?query=*` 与 `*?city=*`**，而列表页正是这种 URL → `PermissionError`，请求未发出 |
| 纯 HTTP | 返回 JS 空壳（`加载中，请稍候` + `browser-check-v2.js`），无任何岗位 |
| 真实 Chrome | 首次可过指纹校验但结果区为空；再次请求直接返回「安全验证」 |

> 注意：`?query=` / `?city=` 是站方在 robots 里**显式声明禁止**的路径。
> 岗位字段本身是公开的，但「公开可见」与「站方允许自动化访问」是两件事，
> robots 表达的是后者。因此本项目按第 5 条硬约束直接拒绝，不做任何绕过。

启用前置条件（缺一不可）：法务书面意见 → 写入 `approval_note` → 评估 browser 模式的稳定性与频率。

#### 4.1.1 CDP 旁听模式（`BOSS_MODE=cdp`，实测可用）

适配器连接本机**已登录**的 Chrome（`--remote-debugging-port=9223`），旁听页面自身发出的
`joblist.json`，拿接口层**明文** `salaryDesc`（DOM 里是字体加密的 `-K` 乱码）。
不注入 XHR、不伪造指纹、不接代理池，只读旁听。

```bash
tools\start_boss_chrome.bat          # 1. 启动独立 Chrome 并手动登录 BOSS
set BOSS_MODE=cdp                    # 2. 切到 cdp 模式
python -m jobmvp.cli run boss --trigger manual
```

实测：1 页 15 条，六项字段 100%、薪资可解析 100%、岗类映射 100%。
前提：Chrome 常驻且登录态有效（过期需重新扫码）。`max_pages=1` 只抓第一页（最新发布）。

### 4.2 外部数据导入（推荐路径）

BOSS 的 robots 禁止自动化采集，直接抓取不可行。若你已有合法数据（例如在**自己的登录态**下
用第三方工具低频导出、或商务授权导出），用导入器并入本项目，复用全部标准化与指标链路：

```bash
python tools/import_boss.py path/to/jobs.json --dry-run   # 先预览映射，不写库
python tools/import_boss.py path/to/jobs.json             # 写库
```

- 支持数组、`{jobList:[...]}`、`{zpData:{jobList:[...]}}` 三种 JSON 结构；
- 字段宽松映射（`jobName`/`salaryDesc`/`brandName`/`cityName`/`areaDistrict`/`jobExperience`/`jobDegree`）；
- **不采 HR 个人信息**：映射层不取 `bossName`/`bossTitle`/`bossAvatar`，白名单 + `sanitize` 再兜底；
- 入库后走 `normalize` + `upsert`，去重、薪资 K、指标、看板自动生效；
- `tools/boss_cdp_smoke.py` 是 CDP 只读自检脚本（验证能否拿到明文 `salaryDesc`），
  需自行用独立 profile 启动 Chrome 并登录后运行。

### 4.3 采集的三种入口（同一份实现）

| 入口 | 用途 |
|---|---|
| 看板「采集配置」→ **立即采集** | 手动触发，按钮旁有实时进度条，状态栏同步显示 |
| **内置调度器** | 勾选「自动采集」+ 设间隔（5-1440 分钟，默认 180），服务进程内按 `last_run_at` 判到期；上轮被风控则强制冷却 180 分钟 |
| `tools/boss_api_scrape.py --plan` | 命令行/排障用，与上面两个共用 `jobmvp/boss_collect.py` |

> 采集**不依赖宿主定时任务**：调度器是服务进程内的守护线程（`jobmvp/scheduler.py`），
> 换机器/换宿主都不影响。宿主的 automation 已停用。

#### 主动调 API 采集（`tools/boss_api_scrape.py`）

在已登录页面上下文里直接调 `joblist.json`（复用 cookie），**30 条/页**，比旁听一页 15 条快一倍：

```bash
# 单次：关键词 × 城市 × 页数
python tools/boss_api_scrape.py --keyword 开发 --city 101110100 --pages 3

# 按看板「采集配置」里保存的计划批量跑（与「立即采集」按钮同一份实现）
python tools/boss_api_scrape.py --plan
```

- 用 `page.request.get()` 而非 `page.evaluate(fetch)` —— 后者遇 SPA 导航会 `Execution context destroyed`；
- 翻页随机延迟 12-22 秒，单次上限 10 页（300 条）；
- 城市码：北京 `101010100` / 上海 `101020100` / 成都 `101270100` / 重庆 `101040100` / 西安 `101110100`。

### 4.4 看板功能与配置

看板地址 `http://127.0.0.1:8010/ui?key=<JOBMVP_API_KEY>`，左侧可折叠菜单 5 个模块：

| 模块 | 内容 |
|---|---|
| 概览 | KPI、数据质量、数据源、新发岗位趋势 |
| 市场结构 | 岗类分布、城市分布、业务领域分布 |
| 技能需求 | 技能热度 Top15、技能×岗类热力矩阵 |
| 薪资分析 | 薪资分位、薪资分布直方图、经验要求分布 |
| 岗位明细 | 在招岗位（岗类/**行业**/城市筛选、搜索、分页）、运行历史、未映射、审计日志 |
| 求职意向 | 期望城市/薪资/技能/岗类 → 岗位匹配度打分（0-100） |
| 采集配置 | 立即采集按钮 + 自动采集开关 + 间隔分钟 + 关键词/城市/页数 |

**底部状态栏**（30 秒轮询，缓存见括号）：

| 项 | 含义 |
|---|---|
| 监控 | 采集计划是否启用 |
| 最近采集 | 距今多久（来自 `max(last_seen)`） |
| 运行 | 服务进程运行时长 |
| 网络 | 外网可达性（60 秒缓存） |
| 账号 | **BOSS 账号真实探测**：调一次 joblist 看 `code` 是否为 0（120 秒缓存） |
| 数据源 | 已启用源数 / 总数 |

账号状态三档：`ok` 正常 / `warn` 异常（`code=36` 需在浏览器完成验证、`code=37/401/403` 登录失效）/ `bad` Chrome 未启动。

### 4.5 采集日志监控

**为什么需要**：`run_log` 只记一次运行的汇总（fetched/parsed/upserted），出问题无法定位是"哪一步、为什么"。

**表 `scrape_step_log`**（`sql/007`）：每一步（关键词 × 城市 × 页）一行

| 字段 | 含义 |
|---|---|
| `run_id` | 关联 `run_log` |
| `keyword` / `city_code` / `city_name` / `page` | 这一步采的是什么 |
| `job_count` | 返回条数 |
| `code` | 接口返回码（BOSS：0=正常 / 36=风控 / 37=登录失效） |
| `elapsed_ms` | 耗时 |
| `status` | `ok` / `empty`（无数据）/ `error`（请求异常） |
| `error` | 异常类型与消息 |

**看板「采集配置」页**下方即「采集日志」卡片：

- 顶部摘要：近 24h 步数 / 异常数 / 空页数 / 平均耗时
- 表格：时间、关键词、城市、页、条数、code、耗时、状态、异常
- **「只看异常」** 勾选框：快速定位失败步骤
- 「刷新」按钮：手动拉最新

**接口**：`GET /api/scrape_logs?limit=30&only_error=1`（返回 `rows` + `summary_24h`）

**排查套路**：

| 现象 | 先看什么 |
|---|---|
| 采集条数突然变 0 | 日志里 `code` 是否变成 36/37；`status` 是否全 `empty` |
| 采集变慢 | `elapsed_ms` 是否异常高（网络或页面卡） |
| 入库数少于抓取数 | `run_log` 的 `parse_failed` + `parse_error` 表 |
| 定时任务没跑 | 状态栏「最近采集」多久前 + `run_log` 最近时间 |

### 4.6 运行日志（实时）

**位置**：看板「采集配置」页最下方的「运行日志（实时）」卡片。

**来源**：两个日志文件（均已加入 `.gitignore`）

| 文件 | 内容 | 写入方 |
|---|---|---|
| `logs/app.log` | 服务启动、HTTP 访问、应用异常、状态探测 | `console/app.py` |
| `logs/scrape.log` | 采集过程关键信息（计划、每步 code/条数/耗时、入库、完成） | `tools/boss_api_scrape.py` |

**内容**：
- 服务：uvicorn 启动/关闭、HTTP 访问日志（`GET /api/... 200`）、应用异常
- 采集：`采集计划：5 词 × 3 城 × 2 页`、`--- 西安 / 开发 第 1 页 ---`、`code=0 岗位数=30 耗时=405ms`、`入库: {new: 1, ...}`、`采集完成，共 30 条`

**查看方式**：

| 方式 | 说明 |
|---|---|
| 看板卡片 | 默认 5 秒自动刷新；**来源下拉**（全部日志 / 服务日志 / 采集日志）；显示行数与文件大小；滚动到底部自动跟随 |
| 接口 | `GET /api/logs/tail?lines=200&source=all\|app\|scrape` |
| 本地文件 | `EmploymentAnalysis/logs/app.log`、`logs/scrape.log` |

**注意**：
- 只给 root logger 挂文件 handler —— `uvicorn.error` 的 `propagate=True` 会冒泡，再单独挂会写两遍；
- `uvicorn.access` 的 `propagate=False`，必须单独挂；
- `httpx` 的 INFO 太吵（状态栏 10 秒轮询会刷屏），已降到 WARNING；
- 采集是**独立进程**，用 `FileHandler`（追加）而非 `RotatingFileHandler`，避免多进程抢滚动文件；
- 合并两个文件时按时间戳字符串排序（格式统一 `%Y-%m-%d %H:%M:%S`，字符串序即时间序）。

---

## 5. 合规约束（不可绕过）

1. 未启用的源**不发请求**（`SourceDisabled` 在 fetch 之前抛）。
2. B 级来源启用必须有 `approval_note`，库级 `CHECK` 兜底。
3. 字段白名单 `whitelist ∩ ALLOWED_FIELDS − PII_FIELDS`。
4. PII 即便误入白名单也丢弃。
5. `robots.txt` 不可达 = 全部禁止。
6. 遇 403/429/验证码 → `CaptchaDetected`，**不重试、不绕过、不判下架**。
7. 只有 `status='success'` 且覆盖率 ≥ `min_coverage` 才做下架判定。
8. 下架需连续 `close_after_miss`（默认 3）次未见。
9. 单条解析失败进 `parse_error`；失败率 >20% 记 `partial`。
10. 分位数样本 <30 不输出；JD 全文不入 `job` 表（只在原始层）。

---

## 6. 指标口径（v1.3）

> **业务去重（v1.2 新增）**：源站会用多个 `job_id` 重复发布同一岗位（公司+岗位+城市+区+薪资相同）。
> `source_job_id` 唯一约束挡不住这种重复。`sql/004_dedup.sql` 建了 `m_job_dedup` 视图，
> 按业务键分组、每组保留 `posted_at` 最新的一条；看板列表与「活跃岗位」类指标均引用它。
> `m_quality` / `m_new_jobs_daily` / `m_job_lifetime` 仍基于原始 `job`（质量诊断、入库量、生命周期口径）。

| 视图 | 口径 |
|---|---|
| `m_job_dedup` | **v1.2 新增**：按 `(title_raw, company_name, city, district, salary_raw)` 去重，保留 `posted_at` 最新（并列取 `first_seen`、`job_pk` 最大）；仅 `active` |
| `m_new_jobs_daily` | 按 `first_seen::date` 计新发（不是 `posted_at`）；基于原始 `job` |
| `m_active_jobs` | **基于 `m_job_dedup`** 计数（去重后活跃数） |
| `m_job_lifetime` | 仅 `closed` 岗位；`closed_at - first_seen` 的 P50；`n≥30` |
| `m_salary_pctl` | v1：`salary_ok AND salary_unit='month' AND min/max 均非空`；`(min+max)/2` 的 P25/P50/P75；按 **(岗类, 城市)** 分组，`n≥30` |
| `m_salary_pctl_by_category` | v1.1 新增 / **v1.2 调整**：只按**岗类**分组并排除 `category IS NULL`；**最小样本 30 → 10**（垂直切口样本稀疏），前端标注「样本<20 谨慎参考」 |
| `m_skill_weekly` | **基于 `m_job_dedup`** `unnest(skills)` 按周 × 岗类 × 技能 |
| `m_quality` | 薪资解析率 / 地区匹配率 / 岗类映射率 / 技能命中率；基于原始 `job` |

**薪资解析（v1.2 扩充）**：除双边界区间外，`X元以上/月`（仅下限）与 `X元以下`（仅上限）也结构化出 `min`/`max`；
仅下限/仅上限不参与薪资分位（分位需 `min`、`max` 均有值），但会进入列表展示（如 `5K以上`）。

### 6.1 P25 / P50 / P75 怎么读

把某个岗类的岗位月薪**从低到高排成一队**：

- **P25**：排在第 1/4 位的薪资 —— 偏低的价，只有 25% 的岗位比它更低；
- **P50（中位数）**：正中间那个 —— 典型水平，一半岗位比它低、一半比它高；
- **P75**：排在第 3/4 位的 —— 偏高的价，只有 25% 的岗位比它更高。

所以 **P25～P75 这个区间，就是「大多数公司开出的价」**。
举例：后端开发 P25 6.5K / P50 9.5K / P75 14.4K，意思是
「四分之一的后端岗低于 6.5K，典型水平 9.5K，四分之一高于 14.4K」。

为什么不用平均值：少数超高薪会把均值拉高，分位数不受极端值影响，更接近真实行情。
样本少于 30 条的岗类不展示分位数（样本太小时分位数没有统计意义）。

口径变更必须升 `METRIC_VERSION` 并留档。

---

## 7. 实测结果

### 7.1 最新一轮（2026-11-02，双源）

| 项 | 值 |
|---|---|
| 明细条数 | 1647（boss 1129 + mohrss 518） |
| 业务去重后 | **1431** |
| 薪资可解析率 | boss 93.2% / mohrss 100% |
| 地区匹配率 | boss 100% / mohrss 86.7% |
| 岗类映射率 | boss 92.1% / mohrss 81.9% |
| 技能命中率 | boss 24.7% / mohrss 46.9% |

单次 mohrss run：60 页 / 523 条解析 / 0 失败 / 138 秒。

### 7.2 早期单源基线（mohrss，60 页 / 1096 条，去重 911）

| 指标 | 全站顺序 | 技术关键词轮转 |
|---|---|---|
| 样本 | 400 | 911 |
| 技术岗占比 | 2~3% | **49.7%**（453 条） |
| 薪资可解析率 | 88.3% | 83.4% |
| 地区匹配率 | 100% | 100% |
| 岗类映射率 | 69.3% | **83.0%** |
| 技能命中率 | 7.3% | **46.3%** |

岗类 Top：后端开发 184 / 未映射 155 / 销售·市场 121 / 职能 78 / 嵌入式·硬件 72 / 测试 60 / 算法·AI 55。

薪资分位（按岗类，n≥30）：后端 P50 9.5K（n=155）、嵌入式 11.0K（n=65）、
算法·AI 14.8K（n=44）、测试 5.0K（n=55）、运维 7.5K（n=34）。

城市 Top：台州 100 / 西安 87 / 昆明 51 / 北京 41 / 无锡 38 / 合肥 34 / 苏州 30；
另有 192 条源站只给省级码（如「江苏省」），按口径留空不臆测。

已知偏差：
- 默认排序（`orderType=score`）按发布机构聚集，单次 20 页里 西安 200 / 东台 137，
  **不是全国代表性样本**；要提升覆盖面需加大 `max_pages` 或改排序参数。
- 该源以蓝领/服务业岗位为主，技术岗占比很低，与产品「技术/AI 切口」不匹配，
  需要补充企业官网/校招官网等 A 级来源。
- `m_salary_pctl` 按 (岗类, 城市) 分组，未映射岗类会形成 `category IS NULL` 的组，
  是否过滤待手册确认（属口径变更）。

---

## 8. 测试

```bash
TEST_DSN=postgresql://mvp:mvp@127.0.0.1:5432/jobmvp_test \
JOBMVP_DSN=postgresql://mvp:mvp@127.0.0.1:5432/jobmvp_test \
JOBMVP_API_KEY=k \
  .venv/Scripts/python.exe -m pytest -q tests
```

**⚠️ 测试会 TRUNCATE 业务表，`TEST_DSN` 与 `JOBMVP_DSN` 必须都指向测试库。**
（`console/app.py` 在 import 时读 `JOBMVP_DSN`，不设置会连到业务库。）

当前：**98 passed**（含 CLI、双源适配器、指标口径、控制台接口、求职意向匹配、采集核心纯函数、采集计划状态回写等）。

最近一次全功能验收（2026-11-02）：**71 测试通过 · 26 个接口全通 · 7 个看板模块无异常 · mohrss 真实采集 60 页 523 条入库**，详见 [`docs/验收-全功能流程.md`](docs/验收-全功能流程.md)。

---

## 9. 重置数据库

口令**不要写进命令历史和仓库**，用环境变量传：

```bash
export PGPASSWORD="<你的 postgres 口令>"      # Windows: $env:PGPASSWORD = "..."
.venv/Scripts/python.exe - <<'PY'
import os, psycopg
dsn = "postgresql://postgres:{pw}@127.0.0.1:5432/postgres".format(pw=os.environ["PGPASSWORD"])
with psycopg.connect(dsn, autocommit=True) as c:
    for db in ("jobmvp", "jobmvp_test"):
        c.execute("DROP DATABASE IF EXISTS {db} WITH (FORCE)".format(db=db))
        c.execute("CREATE DATABASE {db} TEMPLATE postgres OWNER mvp".format(db=db))
PY
```

> 早期版本这里写死过本机超级用户口令，已在全部 git 历史中清除；克隆历史副本仍可能看到，请视情况轮换。

> **本机坑**：这个 PostgreSQL 实例的 `template0` 数据目录缺失（`base/4` 不存在），
> `CREATE DATABASE ... TEMPLATE template0` 会报
> `无法打开文件 "base/4/pg_filenode.map"`。改用 `TEMPLATE postgres` 即可。
> 如需修好 template0，需以单用户模式重建该库，属运维操作，暂不处理。

---

## 10. 许可

本项目采用 **Apache License 2.0**（见 [`LICENSE`](LICENSE) 与 [`NOTICE`](NOTICE)）。

- 允许商用、修改、再分发；分发修改版需保留原许可声明并标注改动。
- 含**专利授权**（第 3 条）与**免责条款**（第 7、8 条）；**不授予商标使用权**（第 6 条）。
- 换许可只需替换 `LICENSE` 文件与本节：想要「修改必须开源」→ AGPL-3.0；想要最短文本 → MIT。

提交前自检凭据：`.venv/Scripts/python.exe tools/scan_secrets.py`（工作区 + 全历史，命中退出码 1）。
