"""业务去重：m_job_dedup 按 (岗位+公司+城市+区+薪资) 合并，每组保留 posted_at 最新。"""
import psycopg
from jobmvp import store

def _insert(conn, rows):
    for sid, title, city, district, sal, comp, posted in rows:
        conn.execute(
            """INSERT INTO job(source_id,source_job_id,title_raw,city,district,
                              salary_raw,company_name,status,posted_at,content_hash)
               VALUES ('fx',%s,%s,%s,%s,%s,%s,'active',%s, md5(%s))""",
            (sid, title, city, district, sal, comp, posted, sid))
    conn.commit()

def test_dedup_keeps_latest_posted(conn):
    _insert(conn, [
        ("a", "Java开发", "西安", "雁塔区", "5000-8000元/月", "觉醒", "2026-09-18"),
        ("b", "Java开发", "西安", "雁塔区", "5000-8000元/月", "觉醒", "2026-10-26"),  # 最新
        ("c", "Java开发", "西安", "雁塔区", "5000-8000元/月", "觉醒", "2026-09-18"),
    ])
    ids = [r["source_job_id"] for r in conn.execute("SELECT source_job_id FROM m_job_dedup ORDER BY 1")]
    assert ids == ["b"]                                  # 同业务组只留最新发布那条

def test_dedup_keeps_distinct_business_keys(conn):
    _insert(conn, [
        ("x", "Java开发", "西安", "雁塔区", "5000-8000元/月",  "A", "2026-10-01"),
        ("y", "Java开发", "西安", "雁塔区", "8000-12000元/月", "A", "2026-10-01"),  # 薪资不同
        ("z", "Java开发", "成都", "高新区", "5000-8000元/月",  "A", "2026-10-01"),  # 城市不同
    ])
    n = conn.execute("SELECT count(*) n FROM m_job_dedup").fetchone()["n"]
    assert n == 3                                       # 不同业务组全部保留

def test_dedup_excludes_closed(conn):
    conn.execute("""INSERT INTO job(source_id,source_job_id,title_raw,city,district,
                       salary_raw,company_name,status,posted_at,content_hash)
                   VALUES ('fx','c1','测试岗','北京','海淀区','10-20K','B','closed','2026-10-01', md5('c1'))""")
    conn.commit()
    assert conn.execute("SELECT count(*) n FROM m_job_dedup").fetchone()["n"] == 0
