# EmploymentAnalysis · 招聘市场数据 MVP

按 `docs/招聘市场实时数据分析与可视化产品方案.md` 与 `reference/jobmvp-参考实现/` 的约束实现的最小可用版本（M1 数据底座）。

**当前状态**：链路已跑通 —— 真实 A 级数据源 → 原始层落盘 → 解析 → 标准化 → PostgreSQL → 指标视图 → 控制台 API。
**尚未做**：前端看板、调度（cron/systemd）、多租户与权限。等 MVP 手册确认后再排期。

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

控制台接口（均需 `X-API-Key`，未配置 `JOBMVP_API_KEY` 时一律 401）：

| 接口 | 用途 |
|---|---|
| `GET /api/sources` | 源列表 + 最近一次运行 |
| `POST /api/sources/{id}/enable` | 启停源（B 级必须带 `approval_note`） |
| `POST /api/sources/{id}/run` | 触发运行（202，后台执行） |
| `GET /api/sources/{id}/runs` | 运行历史 |
| `GET /api/runs/{run_id}/errors` | 解析失败样本 |
| `GET /api/quality` | 数据质量面板 |
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
│   ├── cli.py            run / reap（cron 入口）
│   └── sources/
│       └── mohrss.py     中国公共招聘网适配器（A 级）
├── console/app.py        FastAPI 控制台
├── sql/                  001 表结构 / 002 指标视图
├── tools/seed_dicts.py   字典与源配置播种
├── tests/                52 个用例（需真实 PG）
├── data/raw/             原始层：按 source/日期 落盘，可重放
├── docs/                 产品方案、参考项目调研、架构笔记
└── reference/            三套参考工程（不入库）
```

---

## 4. 数据源

| source_id | 名称 | 等级 | 状态 | 说明 |
|---|---|---|---|---|
| `mohrss` | 中国公共招聘网 | **A** | 已接入，运行中 | 人社部公共就业平台公开列表页；无登录、无验证码；约 17 万条岗位 |
| `boss` | BOSS直聘 | **B** | 已接入，**默认关闭** | 代码与解析器就位，但受 robots 与风控限制，当前拿不到数据（见下） |

采集口径：
- 只读列表页，**不进详情页**；单页 20 条；`min_interval_s=2`。
- 薪资：`acb241/acb242` 合成 `"8000-12000元/月"` 交给 `normalize.parse_salary`，落库为**千元/月**。
- 地区：只用 `aab302`（工作地）+ `aab301`（区划码），**不用 `acb202`** ——
  后者是单位注册地址，实测常与工作地不符（标"西安市"、地址在湖北武汉）。
  区县级岗位用同页学到的「区划码前 4 位 → 城市」归并。
- PII：源站列表含 `aae004`（联系人）/`aae005`（电话）/`aae013`（邮箱），
  适配器**根本不读取**这些键，加上 `sanitize()` 的 `PII_FIELDS` 双保险。

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

## 6. 指标口径（v1）

| 视图 | 口径 |
|---|---|
| `m_new_jobs_daily` | 按 `first_seen::date` 计新发（不是 `posted_at`） |
| `m_active_jobs` | `status='active'` 计数 |
| `m_job_lifetime` | 仅 `closed` 岗位；`closed_at - first_seen` 的 P50；`n≥30` |
| `m_salary_pctl` | `active AND salary_ok AND salary_unit='month'`；`(min+max)/2` 的 P25/P50/P75；`n≥30` |
| `m_skill_weekly` | `unnest(skills)` 按周 × 岗类 × 技能 |
| `m_quality` | 薪资解析率 / 地区匹配率 / 岗类映射率 / 技能命中率 |

口径变更必须升 `METRIC_VERSION` 并留档。

---

## 7. 首次实测结果（mohrss，20 页 / 400 条）

| 指标 | 值 | 说明 |
|---|---|---|
| 解析成功 | 400 / 400 | `parse_failed=0` |
| 薪资可解析率 | 88.3% | 其余为「面议」或仅给下限 |
| 地区匹配率 | 100% | 用源站自带区划码 |
| 岗类映射率 | 69.3% | 未映射进 `unmapped_term` 队列 |
| 技能命中率 | 7.3% | 该源岗位描述普遍很短（"有经验者优先"） |

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

当前：**52 passed**（37 个参考实现用例 + 15 个 mohrss 适配器用例）。

---

## 9. 重置数据库

```bash
.venv/Scripts/python.exe - <<'PY'
import psycopg
with psycopg.connect("postgresql://postgres:<REDACTED>@127.0.0.1:5432/postgres", autocommit=True) as c:
    for db in ("jobmvp", "jobmvp_test"):
        c.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {db} TEMPLATE postgres OWNER mvp")
PY
```

> **本机坑**：这个 PostgreSQL 实例的 `template0` 数据目录缺失（`base/4` 不存在），
> `CREATE DATABASE ... TEMPLATE template0` 会报
> `无法打开文件 "base/4/pg_filenode.map"`。改用 `TEMPLATE postgres` 即可。
> 如需修好 template0，需以单用户模式重建该库，属运维操作，暂不处理。
