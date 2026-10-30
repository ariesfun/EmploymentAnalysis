"""控制台后端（MVP P0）：源管理 / 运行 / 错误样本 / 数据质量 / 指标预览 / 审计。"""
from __future__ import annotations
import hmac, json, os
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
                   salary_ok, category, posted_at, first_seen, last_seen, url
            FROM m_job_dedup WHERE {cond}
            ORDER BY {order}
            LIMIT %s OFFSET %s""",
        args + [min(limit, 200), max(offset, 0)],
    ).fetchall()
    return {"total": total, "limit": limit, "offset": offset, "rows": rows}


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
    """业务领域分布（从公司名关键词粗分类，去重后活跃岗位）。"""
    rows = conn.execute(
        """SELECT CASE
                 WHEN company_name ~ '科技|信息|软件|网络|智能|数据' THEN '信息技术'
                 WHEN company_name ~ '财务|会计|税务|金融' THEN '财务金融'
                 WHEN company_name ~ '轨道|交通|运输|物流|供应链' THEN '交通物流'
                 WHEN company_name ~ '安全' THEN '安全'
                 WHEN company_name ~ '芯|半导体|电子' THEN '电子芯片'
                 WHEN company_name ~ '医疗|医药|生物' THEN '医疗健康'
                 WHEN company_name ~ '教育|培训|学校' THEN '教育培训'
                 WHEN company_name ~ '制造|机械|设备|工业' THEN '制造工业'
                 WHEN company_name ~ '贸易|商贸' THEN '商贸'
                 ELSE '其他' END AS domain,
               count(*) AS n
           FROM m_job_dedup GROUP BY 1 ORDER BY 2 DESC"""
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
    conn.execute(
        """INSERT INTO scrape_plan(source_id, keywords, cities, pages_per_combo, enabled, updated_at)
           VALUES (%s,%s,%s::jsonb,%s,%s,now())
           ON CONFLICT (source_id) DO UPDATE SET
             keywords=EXCLUDED.keywords, cities=EXCLUDED.cities,
             pages_per_combo=EXCLUDED.pages_per_combo,
             enabled=EXCLUDED.enabled, updated_at=now()""",
        (source_id, keywords, json.dumps(cities, ensure_ascii=False), pages, enabled),
    )
    conn.commit()
    return {"ok": True, "source_id": source_id, "keywords": keywords, "cities": cities,
            "pages_per_combo": pages, "enabled": enabled}


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
                 WHEN exp_min_years IS NULL THEN '未标注'
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
