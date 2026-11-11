import os, subprocess, uuid
from pathlib import Path

import pytest
from jobmvp import store
from jobmvp.env import load_env

load_env()                                                   # 允许用 .env 里的测试库连接串
DSN = os.environ.get("TEST_DSN", "postgresql://mvp:mvp@localhost/jobmvp")
# 安全阀：.env 里的 JOBMVP_DSN 指向**业务库**，而测试 fixture 会 TRUNCATE 业务表。
# 这里强制把 JOBMVP_DSN 也指向测试库，避免开发机上跑一次 pytest 就把真实数据清空。
os.environ["JOBMVP_DSN"] = DSN

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


@pytest.fixture()
def raw_dir():
    """原始层落盘目录。

    刻意不用 pytest 的 `tmp_path`：它在会话结束时会走 `shutil.rmtree` 批量删除，
    而本机 `%TEMP%` 是拒绝访问的（WinError 5），宿主的删除守卫建不了锁就会
    `SystemExit(1)` —— 表现为"所有用例都过但退出码是 1、且不打印汇总"。
    这里改用项目内 .tmp/ 下的唯一目录，不删（已被 .gitignore 忽略）。
    """
    d = Path(__file__).resolve().parent.parent / ".tmp" / "tests" / uuid.uuid4().hex[:8]
    d.mkdir(parents=True, exist_ok=True)
    return d
