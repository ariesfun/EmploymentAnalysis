"""入库与生命周期。所有写入走参数化 SQL。"""
from __future__ import annotations
import hashlib, json
from typing import Optional
import psycopg
from psycopg.rows import dict_row

def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=False)

def audit(conn, actor: str, action: str, target: str | None = None, detail: dict | None = None) -> None:
    conn.execute("INSERT INTO audit_log(actor,action,target,detail) VALUES (%s,%s,%s,%s)",
                 (actor, action, target, json.dumps(detail or {}, ensure_ascii=False)))

def load_source(conn, source_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM source_config WHERE source_id=%s", (source_id,)).fetchone()

def start_run(conn, source_id: str, trigger: str) -> int:
    return conn.execute("INSERT INTO run_log(source_id,trigger) VALUES (%s,%s) RETURNING run_id",
                        (source_id, trigger)).fetchone()["run_id"]

def finish_run(conn, run_id: int, status: str, error: str | None = None, **counters) -> None:
    conn.execute("""UPDATE run_log SET finished_at=now(), status=%s, error=%s,
                    fetched=%s, parsed=%s, upserted=%s, parse_failed=%s, closed=%s WHERE run_id=%s""",
                 (status, error, counters.get("fetched", 0), counters.get("parsed", 0),
                  counters.get("upserted", 0), counters.get("parse_failed", 0), counters.get("closed", 0), run_id))

def log_parse_error(conn, run_id: int, url: str, reason: str, snippet: str) -> None:
    conn.execute("INSERT INTO parse_error(run_id,url,reason,snippet) VALUES (%s,%s,%s,%s)",
                 (run_id, url, reason[:500], snippet[:500]))

def last_success_parsed(conn, source_id: str) -> Optional[int]:
    r = conn.execute("""SELECT parsed FROM run_log WHERE source_id=%s AND status='success'
                        ORDER BY started_at DESC LIMIT 1""", (source_id,)).fetchone()
    return r["parsed"] if r else None

def content_hash(rec: dict) -> str:
    keys = ("title_raw", "salary_raw", "experience_raw", "location_raw", "company_name", "description")
    payload = json.dumps({k: rec.get(k) for k in keys}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()

def upsert_job(conn, run_id: int, source_id: str, rec: dict) -> str:
    """rec 为已标准化记录。返回事件：new / changed / reopened / seen。"""
    row = conn.execute("SELECT job_pk,status,content_hash FROM job WHERE source_id=%s AND source_job_id=%s FOR UPDATE",
                       (source_id, rec["source_job_id"])).fetchone()
    cols = ["url", "title_raw", "category", "city", "district", "region_code", "salary_raw", "salary_unit",
            "salary_min", "salary_max", "salary_months", "salary_ok", "exp_min_years", "exp_max_years",
            "edu", "company_name", "skills", "posted_at", "content_hash", "raw_path"]
    vals = [rec.get(c) for c in cols]
    if row is None:
        ph = ",".join(["%s"] * (len(cols) + 3))
        pk = conn.execute(f"INSERT INTO job({','.join(cols)},source_id,source_job_id,last_seen_run) VALUES ({ph}) RETURNING job_pk",
                          vals + [source_id, rec["source_job_id"], run_id]).fetchone()["job_pk"]
        conn.execute("INSERT INTO job_event(job_pk,run_id,event) VALUES (%s,%s,'new')", (pk, run_id))
        return "new"
    event = "seen"
    if row["status"] == "closed":
        event = "reopened"
    elif row["content_hash"] != rec["content_hash"]:
        event = "changed"
    sets = ",".join(f"{c}=%s" for c in cols)
    conn.execute(f"""UPDATE job SET {sets}, last_seen=now(), last_seen_run=%s, miss_count=0,
                     status='active', closed_at=NULL WHERE job_pk=%s""", vals + [run_id, row["job_pk"]])
    if event != "seen":
        conn.execute("INSERT INTO job_event(job_pk,run_id,event) VALUES (%s,%s,%s)", (row["job_pk"], run_id, event))
    return event

def sweep_closed(conn, source_id: str, run_id: int, close_after_miss: int) -> int:
    """仅在“完整且覆盖达标”的运行后调用。未见岗位 miss+1，连续 N 次未见才判下架。"""
    conn.execute("""UPDATE job SET miss_count = miss_count + 1
                    WHERE source_id=%s AND status='active' AND last_seen_run IS DISTINCT FROM %s""", (source_id, run_id))
    rows = conn.execute("""UPDATE job SET status='closed', closed_at=now()
                           WHERE source_id=%s AND status='active' AND miss_count >= %s RETURNING job_pk""",
                        (source_id, close_after_miss)).fetchall()
    for r in rows:
        conn.execute("INSERT INTO job_event(job_pk,run_id,event) VALUES (%s,%s,'closed')", (r["job_pk"], run_id))
    return len(rows)

def bump_unmapped(conn, kind: str, term: str) -> None:
    conn.execute("""INSERT INTO unmapped_term(kind,term) VALUES (%s,%s)
                    ON CONFLICT (kind,term) DO UPDATE SET cnt=unmapped_term.cnt+1, last_seen=now()""", (kind, term))

def reap_stale_runs(conn, max_age_hours: int = 6) -> int:
    """进程崩溃会留下永远 running 的僵尸记录，进而阻塞手动触发；启动/定时调用本函数将其置 failed。"""
    rows = conn.execute("""UPDATE run_log SET status='failed', finished_at=now(), error='stale running reaped'
                           WHERE status='running' AND started_at < now() - make_interval(hours => %s)
                           RETURNING run_id""", (max_age_hours,)).fetchall()
    return len(rows)
