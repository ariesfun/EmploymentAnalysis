"""控制台后端（MVP P0）：源管理 / 运行 / 错误样本 / 数据质量 / 指标预览 / 审计。"""
from __future__ import annotations
import hmac, json, os, threading, time
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
import sys
from contextlib import asynccontextmanager

from jobmvp import boss_collect, store
from jobmvp.scheduler import CollectScheduler
from jobmvp.registry import REGISTRY                     # 与 CLI 共用同一份适配器注册表
from jobmvp.runner import SourceDisabled, run_source
from .ui import router as ui_router

# ---------------------------------------------------------------- 运行日志
import logging
import logging.handlers
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"


def _setup_logging() -> None:
    """把 root / uvicorn 日志同时写入 logs/app.log（5MB × 3 滚动）。"""
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)

    # 只给 root 挂文件 handler：uvicorn.error 的 propagate=True 会自动冒泡到这里，
    # 再单独给 uvicorn.error 挂一份就会写两遍（实测踩过）。
    root = logging.getLogger()
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        root.addHandler(fh)
        root.setLevel(logging.INFO)

    # uvicorn.access 的 propagate=False，不会冒泡，必须单独挂
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in access.handlers):
        access.addHandler(fh)

    # httpx 每个请求都打 INFO，太吵（状态栏 10s 轮询会刷屏），降到 WARNING
    logging.getLogger("httpx").setLevel(logging.WARNING)


_setup_logging()
logger = logging.getLogger("console")

START_TIME = time.time()          # 进程启动时间，用于计算运行时长
DSN = os.environ.get("JOBMVP_DSN", "postgresql://mvp:mvp@localhost/jobmvp")
API_KEY = os.environ.get("JOBMVP_API_KEY", "")
METRIC_VIEWS = {"new_jobs_daily": "m_new_jobs_daily", "active_jobs": "m_active_jobs", "salary_pctl": "m_salary_pctl",
                "salary_by_category": "m_salary_pctl_by_category",
                "job_lifetime": "m_job_lifetime", "skill_weekly": "m_skill_weekly"}   # 白名单，禁止拼接用户输入
METRIC_VERSION = "v1.3"          # v1.3：region_match_pct 改为按 city 判定（兼容无区划码的源，如 BOSS）

# ---------------------------------------------------------------- 内置采集
# 采集不再依赖宿主定时任务：服务进程内自己调度 + 自己执行，进度对看板可见。
_COLLECT_LOCK = threading.Lock()
_COLLECT: dict = {
    "running": False, "phase": "idle", "trigger": None,
    "started_at": None, "finished_at": None,
    "done": 0, "total": 0, "jobs": 0, "upserted": 0,
    "current": "", "message": None, "risk_code": None, "elapsed": 0,
}
_scheduler: CollectScheduler | None = None


def _collect_progress(p: dict) -> None:
    """boss_collect 每翻一页回调一次，只更新内存态（不碰库，避免拖慢采集）。"""
    with _COLLECT_LOCK:
        _COLLECT.update(
            phase=p.get("phase") or _COLLECT["phase"],
            done=p.get("done", _COLLECT["done"]),
            total=p.get("total", _COLLECT["total"]),
            jobs=p.get("jobs", _COLLECT["jobs"]),
            upserted=p.get("upserted", _COLLECT["upserted"]),
            current=p.get("current") or _COLLECT["current"],
            message=p.get("message") or _COLLECT["message"],
        )
        if _COLLECT["started_at"]:
            _COLLECT["elapsed"] = int(time.time() - _COLLECT["started_at"])


def _collect_snapshot(conn) -> dict:
    """采集快照：优先内存态；服务重启后内存清零，则从 scrape_plan 回显上次结果。"""
    with _COLLECT_LOCK:
        snap = dict(_COLLECT)
    if snap["started_at"] and snap["running"]:
        snap["elapsed"] = int(time.time() - snap["started_at"])
    snap["from_db"] = False
    if snap["phase"] == "idle":
        try:
            row = conn.execute(
                "SELECT last_run_at, last_status, last_message FROM scrape_plan WHERE source_id='boss'"
            ).fetchone()
        except Exception:  # noqa: BLE001
            row = None
        if row and row["last_run_at"]:
            ok = row["last_status"] == "success"
            snap.update(
                phase=("done" if ok else "aborted"),
                finished_at=row["last_run_at"].timestamp(),
                message=row["last_message"],
                current=("已完成" if ok else "已停止"),
                from_db=True,
            )
    return snap


def _run_collect(plan: dict, trigger: str) -> None:
    """后台线程执行一轮采集，结束后把结果写回 scrape_plan。"""
    try:
        result = boss_collect.collect(plan, progress=_collect_progress)
    except Exception as e:  # noqa: BLE001  采集线程不能把异常抛给调用方
        logger.exception("采集异常")
        result = {"ok": False, "total": 0, "upserted": 0, "pages_done": 0,
                  "pages_total": 0, "aborted": True, "risk_code": None,
                  "error_kind": "exception", "message": f"{type(e).__name__}: {str(e)[:160]}"}

    status = ("success" if result["ok"] else
              "risk" if result.get("risk_code") else "error")
    with _COLLECT_LOCK:
        _COLLECT.update(
            running=False, phase=("done" if result["ok"] else "aborted"),
            finished_at=time.time(), risk_code=result.get("risk_code"),
            jobs=result["total"], upserted=result["upserted"],
            done=result["pages_done"], total=result["pages_total"],
            current=("已完成" if result["ok"] else "已停止"),
            message=result.get("message") or None,
            elapsed=int(time.time() - (_COLLECT["started_at"] or time.time())),
        )
    try:
        conn = store.connect(DSN)
        conn.execute(
            """UPDATE scrape_plan SET last_status=%s, last_message=%s WHERE source_id='boss'""",
            (status, (result.get("message") or f"抓取 {result['total']} 条")[:300]),
        )
        conn.commit()
        conn.close()
    except Exception:  # noqa: BLE001
        logger.warning("回写采集结果失败", exc_info=True)
    logger.info("采集结束：%s 抓取 %d 条 / 入库 %d", status, result["total"], result["upserted"])


def _trigger_collect(trigger: str = "manual") -> bool:
    """触发一轮采集；已有采集在跑返回 False。调度器和接口都走这里。"""
    with _COLLECT_LOCK:
        if _COLLECT["running"]:
            return False
        conn = None
        try:
            conn = store.connect(DSN)
            row = conn.execute("SELECT * FROM scrape_plan WHERE source_id='boss'").fetchone()
        finally:
            if conn:
                conn.close()
        if not row:
            return False
        plan = dict(row)
        _COLLECT.update(
            running=True, phase="start", trigger=trigger, started_at=time.time(),
            finished_at=None, done=0, total=0, jobs=0, upserted=0,
            current="准备连接 Chrome", message=None, risk_code=None, elapsed=0,
        )
    # 先写 last_run_at，避免调度器在采集期间重复判到期
    try:
        conn = store.connect(DSN)
        conn.execute("UPDATE scrape_plan SET last_run_at=now() WHERE source_id='boss'")
        conn.commit()
        conn.close()
    except Exception:  # noqa: BLE001
        logger.warning("写 last_run_at 失败", exc_info=True)

    threading.Thread(target=_run_collect, args=(plan, trigger),
                     name=f"collect-{trigger}", daemon=True).start()
    logger.info("采集已启动（trigger=%s）", trigger)
    return True


@asynccontextmanager
async def lifespan(_app):
    global _scheduler
    # 测试里不启调度线程（pytest 会 import 本模块）
    if os.environ.get("JOBMVP_SCHEDULER", "1") != "0" and "pytest" not in sys.modules:
        _scheduler = CollectScheduler(DSN, _trigger_collect)
        _scheduler.start()
    yield
    if _scheduler:
        _scheduler.stop()


app = FastAPI(title="jobmvp console", lifespan=lifespan)
app.include_router(ui_router)                                  # 可视化首页 /ui

def auth(x_api_key: str = Header(default="")):
    if not API_KEY or not hmac.compare_digest(x_api_key, API_KEY):   # 未配置 KEY 时一律拒绝，避免裸奔上线
        raise HTTPException(401, "unauthorized")
    return "console-user"

def db():
    conn = store.connect(DSN)
    try:
        yield conn
    finally:
        conn.close()

class EnableBody(BaseModel):
    enabled: bool
    approval_note: str | None = None

@app.get("/api/sources")
def sources(_=Depends(auth), conn=Depends(db)):
    rows = conn.execute("""SELECT s.source_id,s.name,s.tier,s.enabled,s.min_interval_s,s.field_whitelist,s.approval_note,
        (SELECT row_to_json(r) FROM (SELECT run_id,status,started_at,finished_at,fetched,parsed,parse_failed,closed,error
                                     FROM run_log WHERE source_id=s.source_id ORDER BY started_at DESC LIMIT 1) r) AS last_run
        FROM source_config s ORDER BY s.source_id""").fetchall()
    # BOSS 每翻一页就写一条 run_log，last_run 只是"最后一页 30 条"，
    # 会让人以为整轮只采了 30 条。这里补一个整轮汇总（来自 scrape_plan）。
    plan = conn.execute(
        "SELECT last_run_at, last_status, last_message FROM scrape_plan WHERE source_id='boss'"
    ).fetchone()
    for r in rows:
        if r["source_id"] == "boss" and plan:
            r["collect"] = plan
    return rows

@app.post("/api/sources/{source_id}/enable")
def set_enabled(source_id: str, body: EnableBody, user=Depends(auth), conn=Depends(db)):
    cfg = store.load_source(conn, source_id)
    if not cfg:
        raise HTTPException(404, "source not found")
    if body.enabled and cfg["tier"] == "B" and not (body.approval_note or "").strip():
        raise HTTPException(422, "B 级来源启用必须填写审批备注（法务意见/审批单号）")
    conn.execute("UPDATE source_config SET enabled=%s, approval_note=coalesce(%s,approval_note), updated_at=now() WHERE source_id=%s",
                 (body.enabled, body.approval_note, source_id))
    store.audit(conn, user, "source_enable" if body.enabled else "source_disable", source_id,
                {"approval_note": body.approval_note})
    conn.commit()
    return {"ok": True}

# 进程内运行占位：接口返回 202 到后台任务真正写 run_log 之间有一段竞态窗口，
# 只查 run_log 会漏判，连点两次就会起两个 run（实测踩过）。这里用带时间戳的
# 占位集合补上窗口，超过 30 分钟视为僵尸自动失效。
_RUNNING_LOCK = threading.Lock()
_RUNNING: dict[str, float] = {}
_RUNNING_TTL = 1800.0


def _run_in_background(source_id: str, user: str):
    conn = store.connect(DSN)
    try:
        run_source(conn, REGISTRY[source_id](), source_id, trigger="manual", actor=user)
    finally:
        conn.close()
        with _RUNNING_LOCK:
            _RUNNING.pop(source_id, None)

@app.post("/api/sources/{source_id}/run", status_code=202)
def trigger(source_id: str, bg: BackgroundTasks, user=Depends(auth), conn=Depends(db)):
    cfg = store.load_source(conn, source_id)
    if not cfg:
        raise HTTPException(404, "source not found")
    if not cfg["enabled"]:
        raise HTTPException(409, "source disabled")
    if source_id not in REGISTRY:
        raise HTTPException(501, "no adapter registered")
    # BOSS 必须走内置采集（CDP + joblist）：
    # BossAdapter 的 http 模式会被 robots.txt 拒绝（PermissionError），
    # 任何调用方（看板/脚本/curl）打这个接口都应该得到正确行为。
    if source_id == "boss":
        if not _trigger_collect("manual"):
            with _COLLECT_LOCK:
                running = _COLLECT["running"]
            raise HTTPException(409, "采集进行中" if running else "无采集计划")
        return {"accepted": True, "via": "collect"}
    with _RUNNING_LOCK:
        now = time.time()
        stale = [k for k, ts in _RUNNING.items() if now - ts > _RUNNING_TTL]
        for k in stale:
            _RUNNING.pop(k, None)
        if source_id in _RUNNING:
            raise HTTPException(409, "already running")
        if conn.execute("SELECT 1 FROM run_log WHERE source_id=%s AND status='running'",
                        (source_id,)).fetchone():
            raise HTTPException(409, "already running")               # 防止并发重复运行造成 miss 计数错乱
        _RUNNING[source_id] = now                                     # 先占位，堵住 202 到后台启动之间的窗口
    bg.add_task(_run_in_background, source_id, user)
    return {"accepted": True}

@app.get("/api/sources/{source_id}/runs")
def runs(source_id: str, limit: int = 20, _=Depends(auth), conn=Depends(db)):
    return conn.execute("SELECT * FROM run_log WHERE source_id=%s ORDER BY started_at DESC LIMIT %s",
                        (source_id, min(limit, 200))).fetchall()

@app.get("/api/runs/{run_id}/errors")
def run_errors(run_id: int, limit: int = 50, _=Depends(auth), conn=Depends(db)):
    return conn.execute("SELECT url,reason,snippet,at FROM parse_error WHERE run_id=%s ORDER BY id LIMIT %s",
                        (run_id, min(limit, 500))).fetchall()

@app.get("/api/quality")
def quality(_=Depends(auth), conn=Depends(db)):
    return conn.execute("SELECT * FROM m_quality ORDER BY source_id").fetchall()

@app.get("/api/unmapped")
def unmapped(limit: int = 100, _=Depends(auth), conn=Depends(db)):
    return conn.execute("SELECT kind,term,cnt,last_seen FROM unmapped_term ORDER BY cnt DESC LIMIT %s", (min(limit, 500),)).fetchall()

@app.get("/api/metrics/{name}")
def metric(name: str, limit: int = 200, _=Depends(auth), conn=Depends(db)):
    view = METRIC_VIEWS.get(name)
    if not view:
        raise HTTPException(404, "unknown metric")
    rows = conn.execute(f"SELECT * FROM {view} LIMIT %s", (min(limit, 2000),)).fetchall()   # view 来自白名单
    return {"metric": name, "version": METRIC_VERSION, "rows": rows}

@app.get("/api/jobs")
def jobs(category: str = "", city: str = "", q: str = "", sort: str = "posted",
         limit: int = 50, offset: int = 0, _=Depends(auth), conn=Depends(db)):
    """岗位明细（仅当前在招）。用于运营/用户直接跳转源站投递。

    只返回岗位侧字段：不含任何 HR 联系方式（那部分在采集阶段就被丢弃）。
    已按业务键去重（m_job_dedup，每组保留最新发布）；sort 走白名单，禁止拼接用户输入。
    """
    where = ["status = 'active'"]
    args: list = []
    if category:
        where.append("category = %s")
        args.append(category)
    if city:
        where.append("city = %s")
        args.append(city)
    if q:
        where.append("(title_raw ILIKE %s OR company_name ILIKE %s)")
        args += [f"%{q}%", f"%{q}%"]
    cond = " AND ".join(where)
    order = {
        # posted_at 为空（如 BOSS 不提供发布时间）时用 first_seen 兜底，保证新采集的靠前
        "posted":      "COALESCE(posted_at, first_seen) DESC, job_pk DESC",
        "salary_desc": "salary_min DESC NULLS LAST, job_pk DESC",
        "salary_asc":  "salary_min ASC NULLS LAST, job_pk DESC",
    }.get(sort, "COALESCE(posted_at, first_seen) DESC, job_pk DESC")

    total = conn.execute(f"SELECT count(*) AS n FROM m_job_dedup WHERE {cond}", args).fetchone()["n"]
    rows = conn.execute(
        f"""SELECT job_pk, source_id, title_raw, company_name, city, district, salary_raw,
                   salary_min, salary_max, salary_unit, salary_months,
                   salary_ok, category, posted_at, first_seen, last_seen, url
            FROM m_job_dedup WHERE {cond}
            ORDER BY {order}
            LIMIT %s OFFSET %s""",
        args + [min(limit, 200), max(offset, 0)],
    ).fetchall()
    return {"total": total, "limit": min(limit, 200), "offset": offset, "rows": rows}


@app.get("/api/analytics/skills")
def analytics_skills(limit: int = 15, _=Depends(auth), conn=Depends(db)):
    """技能热度 Top N（去重后活跃岗位，unnest skills）。"""
    rows = conn.execute(
        """SELECT s AS skill, count(*) AS n
           FROM m_job_dedup, unnest(skills) AS s
           GROUP BY 1 ORDER BY 2 DESC LIMIT %s""",
        (min(limit, 50),),
    ).fetchall()
    return {"rows": rows}


@app.get("/api/analytics/domains")
def analytics_domains(_=Depends(auth), conn=Depends(db)):
    """业务领域分布。

    两段式判定，避免一大坨「其他」：
    1. **公司名行业词**（IT服务/互联网/电子芯片/制造/医疗…）——最准；
    2. 公司名认不出时，**按岗类反推**（技术岗→信息技术、普工→制造、销售→企业服务），
       这类结果单独计入 inferred_n，前端注明"按岗位推断"，不假装是公司行业。
    """
    rows = conn.execute(
        """WITH d AS (
             SELECT category, company_name,
               CASE
                 WHEN company_name ~ '人力资源|劳务' THEN '人力资源服务'
                 WHEN company_name ~ '中软|软通|法本|德科|慧博云通|中电金信|柯莱特|佰钧成|中科创达|京北方|文思|博彦|东软|太极|神州数码' THEN 'IT服务/外包'
                 WHEN company_name ~ '腾讯|阿里|百度|字节|美团|京东|网易|小米|华为|中兴|快手|滴滴|拼多多|携程' THEN '互联网'
                 WHEN company_name ~ '芯|半导体|集成电路|微电子|晶圆|光电' THEN '电子芯片'
                 WHEN company_name ~ '医疗|医药|生物|制药|医院|基因' THEN '医疗健康'
                 WHEN company_name ~ '教育|培训|学校|学院|职教' THEN '教育培训'
                 WHEN company_name ~ '银行|保险|证券|基金|财务|会计|金融|支付' THEN '金融'
                 WHEN company_name ~ '轨道|交通|运输|物流|供应链|快递|航空|航运' THEN '交通物流'
                 WHEN company_name ~ '汽车|零部件|新能源|锂电' THEN '汽车/新能源'
                 WHEN company_name ~ '建筑|建设|工程|地产|置业|装饰' THEN '建筑地产'
                 WHEN company_name ~ '制造|机械|设备|工业|材料|化工|钢铁' THEN '制造工业'
                 WHEN company_name ~ '传媒|文化|影业|广告|影视' THEN '传媒文化'
                 WHEN company_name ~ '贸易|商贸|零售|超市|电商|百货' THEN '商贸零售'
                 WHEN company_name ~ '科技|信息|软件|网络|智能|数据|云|技术|通信' THEN '信息技术'
                 ELSE NULL END AS dom
             FROM m_job_dedup
           ), b AS (
             SELECT COALESCE(dom,
               CASE
                 WHEN category IN ('后端开发','前端开发','算法/AI','数据','测试','运维/SRE',
                                   '嵌入式/硬件','移动开发','网络安全') THEN '信息技术'
                 WHEN category IN ('销售/市场','职能','产品/项目','设计') THEN '企业服务'
                 WHEN category IN ('普工/操作','机械/制造') THEN '制造工业'
                 WHEN category = '物流/仓储' THEN '交通物流'
                 WHEN category = '建筑/工程' THEN '建筑地产'
                 WHEN category = '教育/培训' THEN '教育培训'
                 WHEN category = '传媒/内容' THEN '传媒文化'
                 WHEN category = '安全/消防' THEN '企业服务'
                 WHEN category = '产品研发(非软件)' THEN '制造工业'
                 ELSE '其他行业' END) AS domain,
               (dom IS NULL) AS inferred
             FROM d
           )
           SELECT domain, count(*) AS n,
                  count(*) FILTER (WHERE inferred) AS inferred_n
           FROM b GROUP BY 1 ORDER BY 2 DESC"""
    ).fetchall()
    return {"rows": rows}


@app.get("/api/analytics/meta")
def analytics_meta(_=Depends(auth), conn=Depends(db)):
    """数据时效信息：最新采集时间、统计窗口起点、去重后条数。"""
    r = conn.execute(
        """SELECT max(last_seen) AS data_as_of,
                  min(first_seen) AS window_start,
                  count(*) AS total
           FROM m_job_dedup"""
    ).fetchone()
    return r


@app.get("/api/scrape_plan")
def get_scrape_plan(source_id: str = "boss", _=Depends(auth), conn=Depends(db)):
    """读取采集计划（关键词 / 城市 / 每组合页数）。"""
    r = conn.execute("SELECT * FROM scrape_plan WHERE source_id=%s", (source_id,)).fetchone()
    return r or {"source_id": source_id, "keywords": [], "cities": [],
                 "pages_per_combo": 2, "enabled": False}


@app.put("/api/scrape_plan")
def put_scrape_plan(body: dict, _=Depends(auth), conn=Depends(db)):
    """保存采集计划。"""
    source_id = body.get("source_id") or "boss"
    keywords = [str(k).strip() for k in (body.get("keywords") or []) if str(k).strip()]
    cities = body.get("cities") or []
    pages = max(1, min(int(body.get("pages_per_combo") or 2), 10))
    enabled = bool(body.get("enabled", True))
    # 间隔 5-1440 分钟：再短会明显加重风控
    interval = max(5, min(int(body.get("interval_minutes") or 60), 1440))
    conn.execute(
        """INSERT INTO scrape_plan(source_id, keywords, cities, pages_per_combo, enabled,
                                   interval_minutes, updated_at)
           VALUES (%s,%s,%s::jsonb,%s,%s,%s,now())
           ON CONFLICT (source_id) DO UPDATE SET
             keywords=EXCLUDED.keywords, cities=EXCLUDED.cities,
             pages_per_combo=EXCLUDED.pages_per_combo,
             enabled=EXCLUDED.enabled,
             interval_minutes=EXCLUDED.interval_minutes, updated_at=now()""",
        (source_id, keywords, json.dumps(cities, ensure_ascii=False), pages, enabled, interval),
    )
    conn.commit()
    return {"ok": True, "source_id": source_id, "keywords": keywords, "cities": cities,
            "pages_per_combo": pages, "enabled": enabled, "interval_minutes": interval}


# ---------------------------------------------------------------- 采集触发与进度

@app.post("/api/collect/start", status_code=202)
def collect_start(_=Depends(auth)):
    """立即采集（手动按钮）。已有采集在跑返回 409。"""
    if not _trigger_collect("manual"):
        with _COLLECT_LOCK:
            running = _COLLECT["running"]
        raise HTTPException(409, "采集进行中" if running else "无采集计划")
    return {"accepted": True}


@app.get("/api/collect/status")
def collect_status(_=Depends(auth), conn=Depends(db)):
    """采集进度（状态栏 / 采集配置页轮询）。"""
    snap = _collect_snapshot(conn)
    snap["scheduler"] = _scheduler.status() if _scheduler else {"alive": False}
    return snap


@app.get("/api/preference")
def get_preference(_=Depends(auth), conn=Depends(db)):
    """读取个人求职意向。"""
    r = conn.execute("SELECT * FROM job_preference WHERE id=1").fetchone()
    return r or {}


@app.put("/api/preference")
def put_preference(body: dict, _=Depends(auth), conn=Depends(db)):
    """保存个人求职意向。"""
    conn.execute(
        """UPDATE job_preference SET
             cities=%s, salary_min=%s, salary_max=%s, skills=%s, categories=%s,
             exp_min=%s, exp_max=%s, updated_at=now()
           WHERE id=1""",
        (body.get("cities") or [], body.get("salary_min"), body.get("salary_max"),
         body.get("skills") or [], body.get("categories") or [],
         body.get("exp_min"), body.get("exp_max")),
    )
    conn.commit()
    return {"ok": True}


@app.get("/api/match_jobs")
def match_jobs(limit: int = 20, min_score: int = 0, _=Depends(auth), conn=Depends(db)):
    """按求职意向匹配的岗位（score 0-100）。"""
    rows = conn.execute(
        """SELECT job_pk, source_id, title_raw, company_name, city, district,
                  salary_raw, salary_min, salary_max, salary_unit, salary_ok,
                  category, skills, url, posted_at, first_seen, score
           FROM m_job_match WHERE score >= %s
           ORDER BY score DESC, salary_max DESC NULLS LAST
           LIMIT %s""",
        (min_score, min(limit, 100)),
    ).fetchall()
    return {"rows": rows}


_NET_CACHE = {"ts": 0.0, "ok": False}


def _check_network() -> bool:
    """探测外网可达性，结果缓存 30 秒，避免状态栏轮询每次都真发请求。"""
    now = time.time()
    if now - _NET_CACHE["ts"] < 30:
        return _NET_CACHE["ok"]
    ok = False
    try:
        import httpx
        r = httpx.get("https://www.zhipin.com", timeout=2.5, follow_redirects=True)
        ok = r.status_code < 500
    except Exception:  # noqa: BLE001
        ok = False
    _NET_CACHE.update({"ts": now, "ok": ok})
    return ok


_BOSS_PROBE = {"ts": 0.0, "state": "unknown", "detail": "未探测"}


def _probe_boss_account(force: bool = False) -> dict:
    """真实探测 BOSS 账号功能是否正常。

    不只看 Chrome 端口，而是通过 CDP 用页面 cookie 调一次 joblist API（pageSize=1），
    看返回 code 是否为 0——这才代表「登录态有效 + 接口可正常调用」。
    结果缓存 60 秒，避免状态栏轮询频繁打 BOSS。
    """
    now = time.time()
    if not force and now - _BOSS_PROBE["ts"] < 60:
        return {"state": _BOSS_PROBE["state"], "detail": _BOSS_PROBE["detail"],
                "checked_at": _BOSS_PROBE["ts"]}

    # 先占位时间戳：并发请求看到 ts 已更新会直接吃缓存，不会重复启动 playwright
    _BOSS_PROBE["ts"] = now

    # 第一步：CDP 端口可达性。不可达一律判 bad（Chrome 没起来），不再往下猜。
    # trust_env=False：本机地址绝不能走系统代理（代理会把 127.0.0.1 也拦掉，误报成探测失败）
    try:
        import httpx
        r = httpx.get("http://127.0.0.1:9223/json/version", timeout=2, trust_env=False)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        detail = f"Chrome 未启动（{type(e).__name__}）"
        _BOSS_PROBE.update({"ts": now, "state": "bad", "detail": detail})
        return {"state": "bad", "detail": detail, "checked_at": now}

    # 第二步：真调一次 joblist，用 code 判断登录态与风控
    state, detail = "warn", "探测失败"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.connect_over_cdp("http://127.0.0.1:9223")
            ctx = b.contexts[0] if b.contexts else b.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            # 必须处在 zhipin.com 上下文，否则 page.request 缺少站点 cookie/头，会返回 code=36
            if "zhipin.com" not in (page.url or ""):
                try:
                    page.goto("https://www.zhipin.com/", wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(1500)
                except Exception:  # noqa: BLE001
                    pass
            resp = page.request.get(
                "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
                "?scene=1&query=%E5%BC%80%E5%8F%91&city=101110100&page=1&pageSize=1",
                timeout=15000,
            )
            data = resp.json()
            code = data.get("code")
            if code == 0:
                state, detail = "ok", "正常 · 登录有效"
            elif code == 35:
                state, detail = "warn", "IP 异常 · 换网络或等冷却"
            elif code == 36:
                state, detail = "warn", "异常 · 需在浏览器完成验证"
            elif code in (37, 401, 403):
                state, detail = "warn", f"失效 · 请重新登录（{code}）"
            else:
                state, detail = "warn", f"接口异常（code={code}）"
    except Exception as e:  # noqa: BLE001
        # 走到这里说明 Chrome 是通的，但 CDP/接口调用失败（多半是页面导航中或超时）
        state, detail = "warn", f"探测失败（{type(e).__name__}）"

    _BOSS_PROBE.update({"ts": now, "state": state, "detail": detail})
    return {"state": state, "detail": detail, "checked_at": now}


@app.get("/api/status")
def get_status(refresh: int = 0, _=Depends(auth), conn=Depends(db)):
    """底部状态栏：监控/采集/运行时长/网络/账号/数据源。"""
    last = conn.execute("SELECT max(last_seen) AS t FROM job").fetchone()["t"]
    plan = conn.execute(
        "SELECT enabled, interval_minutes, last_run_at, last_status, last_message "
        "FROM scrape_plan WHERE source_id='boss'"
    ).fetchone()
    srcs = conn.execute("SELECT source_id, enabled FROM source_config ORDER BY source_id").fetchall()
    collect = _collect_snapshot(conn)
    return {
        "monitor": bool(plan and plan["enabled"]),
        "last_scrape_at": last,
        "uptime_seconds": int(time.time() - START_TIME),
        "network_ok": _check_network(),
        "server_time": time.time(),
        "boss_account": _probe_boss_account(force=bool(refresh)),
        "sources": [{"source_id": x["source_id"], "enabled": x["enabled"]} for x in srcs],
        "collect": collect,
        "plan": ({"enabled": plan["enabled"],
                  "interval_minutes": plan["interval_minutes"],
                  "last_run_at": plan["last_run_at"],
                  "last_status": plan["last_status"],
                  "last_message": plan["last_message"]} if plan else None),
        "scheduler": _scheduler.status() if _scheduler else {"alive": False},
    }


@app.get("/api/scrape_logs")
def scrape_logs(limit: int = 50, only_error: int = 0, _=Depends(auth), conn=Depends(db)):
    """采集步骤日志：每一步（关键词 × 城市 × 页）的返回码/条数/耗时/异常。"""
    cond = "WHERE status <> 'ok'" if only_error else ""
    rows = conn.execute(
        f"""SELECT id, run_id, source_id, keyword, city_name, page, job_count,
                   code, elapsed_ms, status, error, created_at
            FROM scrape_step_log {cond}
            ORDER BY id DESC LIMIT %s""",
        (min(limit, 200),),
    ).fetchall()
    summary = conn.execute(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE status = 'error') AS errors,
                  count(*) FILTER (WHERE status = 'empty') AS empties,
                  round(avg(elapsed_ms)) AS avg_ms
           FROM scrape_step_log WHERE created_at > now() - interval '24 hours'"""
    ).fetchone()
    return {"rows": rows, "summary_24h": summary}


SCRAPE_LOG = LOG_DIR / "scrape.log"


@app.get("/api/logs/tail")
def logs_tail(lines: int = 200, source: str = "all", _=Depends(auth)):
    """读取运行日志尾部（实时日志查看用）。

    source: all=服务+采集合并（按时间排序）/ app=仅服务 / scrape=仅采集。
    两个文件的时间戳前缀格式一致（%Y-%m-%d %H:%M:%S），合并后字符串排序即时间排序。
    """
    targets: list[tuple[str, Path]] = []
    if source in ("all", "app"):
        targets.append(("app", LOG_FILE))
    if source in ("all", "scrape"):
        targets.append(("scrape", SCRAPE_LOG))

    n = max(10, min(lines, 2000))
    collected: list[str] = []
    total_size = 0
    for _name, path in targets:
        if not path.exists():
            continue
        total_size += path.stat().st_size
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - min(size, n * 400)))
            data = f.read().decode("utf-8", errors="replace")
        collected.extend(data.splitlines())

    collected.sort()
    return {"lines": collected[-n:], "files": [str(p) for _, p in targets], "size": total_size}


@app.get("/api/analytics/salary_hist")
def analytics_salary_hist(step: int = 5, _=Depends(auth), conn=Depends(db)):
    """薪资区间分布直方图（月薪 K，按 step 分桶）。"""
    rows = conn.execute(
        """SELECT (floor(((salary_min + salary_max) / 2) / %s) * %s)::int AS lo,
                  count(*) AS n
           FROM m_job_dedup
           WHERE salary_ok AND salary_unit = 'month'
             AND salary_min IS NOT NULL AND salary_max IS NOT NULL
           GROUP BY 1 ORDER BY 1""",
        (step, step),
    ).fetchall()
    return {"step": step, "rows": rows}


@app.get("/api/analytics/experience")
def analytics_experience(_=Depends(auth), conn=Depends(db)):
    """经验要求分布。"""
    rows = conn.execute(
        """SELECT CASE
                 WHEN exp_min_years IS NULL THEN '源未提供'
                 WHEN exp_min_years = 0 AND coalesce(exp_max_years, 0) = 0 THEN '应届/不限'
                 WHEN exp_min_years <= 1 THEN '1年以内'
                 WHEN exp_min_years <= 3 THEN '1-3年'
                 WHEN exp_min_years <= 5 THEN '3-5年'
                 WHEN exp_min_years <= 10 THEN '5-10年'
                 ELSE '10年以上' END AS bucket,
               count(*) AS n
           FROM m_job_dedup GROUP BY 1 ORDER BY 2 DESC"""
    ).fetchall()
    return {"rows": rows}


@app.get("/api/analytics/skill_matrix")
def analytics_skill_matrix(top: int = 8, _=Depends(auth), conn=Depends(db)):
    """技能 × 岗类矩阵（Top 技能在各岗类的出现次数），用于热力图。"""
    rows = conn.execute(
        """WITH top_skill AS (
             SELECT s AS skill, count(*) AS total
             FROM m_job_dedup, unnest(skills) AS s
             GROUP BY 1 ORDER BY 2 DESC LIMIT %s
           )
           SELECT j.category, s AS skill, count(*) AS n
           FROM m_job_dedup j, unnest(j.skills) AS s
           WHERE j.category IS NOT NULL AND s IN (SELECT skill FROM top_skill)
           GROUP BY 1,2 ORDER BY 3 DESC""",
        (min(top, 20),),
    ).fetchall()
    return {"rows": rows}


@app.get("/api/audit")
def audit_list(limit: int = 100, _=Depends(auth), conn=Depends(db)):
    return conn.execute("SELECT at,actor,action,target,detail FROM audit_log ORDER BY id DESC LIMIT %s", (min(limit, 500),)).fetchall()
