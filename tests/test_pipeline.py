import pytest, psycopg
from jobmvp import store
from jobmvp.adapter import SourceAdapter, RawPage, CaptchaDetected, sanitize
from jobmvp.runner import run_source, SourceDisabled

class Fake(SourceAdapter):
    source_id = "fx"
    def __init__(self, pages, captcha_at=None): self.pages, self.captcha_at = pages, captcha_at
    def discover(self, max_pages): return [f"http://x/p{i}" for i in range(len(self.pages))]
    def fetch(self, url):
        i = int(url.rsplit("p", 1)[1])
        if self.captcha_at == i: raise CaptchaDetected("403")
        return RawPage(url=url, status=200, body=str(i))
    def parse(self, page): return self.pages[int(page.body)]

def J(i, **kw):
    d = dict(source_job_id=str(i), url=f"http://x/j{i}", title_raw="C++开发工程师", location_raw="北京·海淀区",
             salary_raw="20-40K·15薪", experience_raw="3-5年", company_name="A", description="熟悉C++/Qt", hr_name="张三")
    d.update(kw); return d

def run(conn, raw_dir, pages, **kw):
    return run_source(conn, Fake(pages, **kw), "fx", raw_root=raw_dir, sleep=lambda s: None)

def test_end_to_end_and_pii(conn, raw_dir):
    r = run(conn, raw_dir, [[J(1), J(2)], [J(3, salary_raw="面议")]])
    assert r["status"] == "success" and r["parsed"] == 3
    row = conn.execute("SELECT * FROM job WHERE source_job_id='1'").fetchone()
    assert (row["category"], row["city"], row["region_code"], row["salary_min"], row["salary_months"]) == ("C++开发", "北京", "110108", 20, 15)
    assert set(row["skills"]) == {"C++", "Qt"}
    assert not any("hr_name" in k or "张三" in str(v) for k, v in row.items())      # PII 不入库
    assert conn.execute("SELECT salary_ok FROM job WHERE source_job_id='3'").fetchone()["salary_ok"] is False
    assert sanitize({"hr_name": "x", "title_raw": "t"}, ["hr_name", "title_raw"]) == {"title_raw": "t"}

def test_lifecycle_new_changed_closed_reopened(conn, raw_dir):
    base = [J(i) for i in range(3, 12)]                                            # 9 个稳定岗位，保证覆盖率 >= 0.7
    run(conn, raw_dir, [[J(1), J(2)] + base])
    run(conn, raw_dir, [[J(1, salary_raw="30-50K"), J(2)] + base])                # 1 变更
    ev = {r["event"] for r in conn.execute("SELECT event FROM job_event WHERE job_pk=(SELECT job_pk FROM job WHERE source_job_id='1')")}
    assert ev == {"new", "changed"}
    for _ in range(3):
        assert run(conn, raw_dir, [[J(1)] + base])["status"] == "success"        # 2 连续 3 次未见
    assert conn.execute("SELECT status FROM job WHERE source_job_id='2'").fetchone()["status"] == "closed"
    run(conn, raw_dir, [[J(1), J(2)] + base])                                     # 2 重新出现
    row = conn.execute("SELECT status,closed_at,miss_count FROM job WHERE source_job_id='2'").fetchone()
    assert (row["status"], row["closed_at"], row["miss_count"]) == ("active", None, 0)
    assert conn.execute("SELECT count(*) n FROM job_event WHERE event='reopened'").fetchone()["n"] == 1

def test_captcha_halts_and_never_closes(conn, raw_dir):
    run(conn, raw_dir, [[J(1), J(2)]])
    r = run(conn, raw_dir, [[J(1)], [J(2)]], captcha_at=1)
    assert r["status"] == "halted_captcha"
    assert conn.execute("SELECT max(miss_count) m FROM job").fetchone()["m"] == 0   # 中断运行不得推进 miss 计数
    assert conn.execute("SELECT count(*) n FROM audit_log WHERE action='captcha_halt'").fetchone()["n"] == 1

def test_low_coverage_blocks_sweep(conn, raw_dir):
    run(conn, raw_dir, [[J(i) for i in range(10)]])
    for _ in range(4):
        r = run(conn, raw_dir, [[J(0)]])                                           # 只抓到 1/10，低于覆盖阈值
        assert r["status"] == "partial"
    assert conn.execute("SELECT count(*) n FROM job WHERE status='closed'").fetchone()["n"] == 0

def test_parse_failure_is_recorded_not_silent(conn, raw_dir):
    r = run(conn, raw_dir, [[J(1), dict(source_job_id="9")]])                     # 缺 title_raw
    assert r["parse_failed"] == 1
    assert conn.execute("SELECT count(*) n FROM parse_error").fetchone()["n"] == 1

def test_disabled_source_makes_no_request(conn, raw_dir):
    conn.execute("UPDATE source_config SET enabled=false"); conn.commit()
    with pytest.raises(SourceDisabled):
        run(conn, raw_dir, [[J(1)]])

def test_tier_b_requires_approval(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO source_config(source_id,name,tier,enabled,field_whitelist) VALUES ('b','b','B',true,'{}')")
    conn.rollback()

def test_metrics_min_sample_and_unmapped(conn, raw_dir):
    # 注意：岗位用不同公司名，否则业务去重(m_job_dedup)会把同岗合并，样本数骤降
    run(conn, raw_dir, [[J(i, company_name=f"A{i}") for i in range(29)]])
    assert conn.execute("SELECT count(*) n FROM m_salary_pctl").fetchone()["n"] == 0     # n<30 屏蔽
    run(conn, raw_dir, [[J(i, company_name=f"A{i}") for i in range(30)]])
    r = conn.execute("SELECT n,p50_k FROM m_salary_pctl").fetchone()
    assert (r["n"], float(r["p50_k"])) == (30, 30.0)
    run(conn, raw_dir, [[J(100, title_raw="销售经理")]])
    assert conn.execute("SELECT cnt FROM unmapped_term WHERE term='销售经理'").fetchone()["cnt"] == 1
    assert conn.execute("SELECT total FROM m_quality").fetchone()["total"] == 31

def test_one_running_per_source_and_reaper(conn):
    store.start_run(conn, "fx", "manual"); conn.commit()
    with pytest.raises(psycopg.errors.UniqueViolation):
        store.start_run(conn, "fx", "manual")
    conn.rollback()
    assert store.reap_stale_runs(conn, 6) == 0                                   # 未超时不回收
    conn.execute("UPDATE run_log SET started_at = now() - interval '7 hours'"); conn.commit()
    assert store.reap_stale_runs(conn, 6) == 1
    assert conn.execute("SELECT status FROM run_log").fetchone()["status"] == "failed"
    store.start_run(conn, "fx", "manual"); conn.commit()                         # 回收后可再次运行
