import os, subprocess, pytest
from jobmvp import store
DSN = os.environ.get("TEST_DSN", "postgresql://mvp:mvp@localhost/jobmvp")

@pytest.fixture()
def conn():
    c = store.connect(DSN)
    c.execute("TRUNCATE job_event, parse_error, job, run_log, audit_log, unmapped_term, dict_category, dict_skill, dict_region, source_config RESTART IDENTITY CASCADE")
    c.execute("""INSERT INTO source_config(source_id,name,tier,enabled,min_interval_s,field_whitelist)
                 VALUES ('fx','fixture','A',true,1,%s)""",
              (["source_job_id","url","title_raw","location_raw","salary_raw","experience_raw","edu","company_name","description","hr_name"],))
    c.execute("INSERT INTO dict_category(pattern,category) VALUES ('c\\+\\+','C++开发'),('算法','算法')")
    c.execute("INSERT INTO dict_skill VALUES ('C++','C++'),('Qt','Qt'),('Python','Python')")
    c.execute("INSERT INTO dict_region VALUES ('北京','海淀区','110108'),('北京','','110100')")
    c.commit()
    yield c
    c.close()
