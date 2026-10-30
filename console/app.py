"""控制台后端（MVP P0）：源管理 / 运行 / 错误样本 / 数据质量 / 指标预览 / 审计。"""
from __future__ import annotations
import hmac, os
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from jobmvp import store
from jobmvp.registry import REGISTRY                     # 与 CLI 共用同一份适配器注册表
from jobmvp.runner import SourceDisabled, run_source
from .ui import router as ui_router

DSN = os.environ.get("JOBMVP_DSN", "postgresql://mvp:mvp@localhost/jobmvp")
API_KEY = os.environ.get("JOBMVP_API_KEY", "")
METRIC_VIEWS = {"new_jobs_daily": "m_new_jobs_daily", "active_jobs": "m_active_jobs", "salary_pctl": "m_salary_pctl",
                "salary_by_category": "m_salary_pctl_by_category",
                "job_lifetime": "m_job_lifetime", "skill_weekly": "m_skill_weekly"}   # 白名单，禁止拼接用户输入
METRIC_VERSION = "v1.3"          # v1.3：region_match_pct 改为按 city 判定（兼容无区划码的源，如 BOSS）

app = FastAPI(title="jobmvp console")
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
    return conn.execute("""SELECT s.source_id,s.name,s.tier,s.enabled,s.min_interval_s,s.field_whitelist,s.approval_note,
        (SELECT row_to_json(r) FROM (SELECT run_id,status,started_at,finished_at,fetched,parsed,parse_failed,closed,error
                                     FROM run_log WHERE source_id=s.source_id ORDER BY started_at DESC LIMIT 1) r) AS last_run
        FROM source_config s ORDER BY s.source_id""").fetchall()

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

def _run_in_background(source_id: str, user: str):
    conn = store.connect(DSN)
    try:
        run_source(conn, REGISTRY[source_id](), source_id, trigger="manual", actor=user)
    finally:
        conn.close()

@app.post("/api/sources/{source_id}/run", status_code=202)
def trigger(source_id: str, bg: BackgroundTasks, user=Depends(auth), conn=Depends(db)):
    cfg = store.load_source(conn, source_id)
    if not cfg:
        raise HTTPException(404, "source not found")
    if not cfg["enabled"]:
        raise HTTPException(409, "source disabled")
    if source_id not in REGISTRY:
        raise HTTPException(501, "no adapter registered")
    if conn.execute("SELECT 1 FROM run_log WHERE source_id=%s AND status='running'", (source_id,)).fetchone():
        raise HTTPException(409, "already running")                   # 防止并发重复运行造成 miss 计数错乱
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
                   salary_ok, category, posted_at, url
            FROM m_job_dedup WHERE {cond}
            ORDER BY {order}
            LIMIT %s OFFSET %s""",
        args + [min(limit, 200), max(offset, 0)],
    ).fetchall()
    return {"total": total, "limit": limit, "offset": offset, "rows": rows}


@app.get("/api/audit")
def audit_list(limit: int = 100, _=Depends(auth), conn=Depends(db)):
    return conn.execute("SELECT at,actor,action,target,detail FROM audit_log ORDER BY id DESC LIMIT %s", (min(limit, 500),)).fetchall()
