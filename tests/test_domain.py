"""行业判定函数（sql/010_job_domain.sql）的回归测试。

这几个用例都是踩过的：
- 「工业软件」被 工业 抢走 → 必须先判 软件
- 「微电子」要落到 电子芯片，不能落到 信息技术
- 公司名认不出时按岗类推断，而不是直接扔「其他行业」
"""
import pytest

from tests.conftest import DSN
from jobmvp import store


@pytest.fixture()
def conn2():
    c = store.connect(DSN)
    yield c
    c.close()


def dom(conn, company, category=None):
    return conn.execute("SELECT fn_job_domain(%s, %s) AS d", (company, category)).fetchone()["d"]


@pytest.mark.parametrize("company,expected", [
    ("中软国际", "IT服务/外包"),
    ("软通动力", "IT服务/外包"),
    ("腾讯科技", "互联网"),
    ("华创微电子", "电子芯片"),
    ("中微半导体", "电子芯片"),
    ("鼎格工业软件", "信息技术"),      # 工业软件：软件优先于工业
    ("某大型计算机软件公司", "信息技术"),
    ("XX人力资源服务有限公司", "人力资源服务"),
    ("重庆轨道交通集团", "交通物流"),
])
def test_company_domain(conn2, company, expected):
    assert dom(conn2, company) == expected


def test_company_domain_unknown_returns_null(conn2):
    """认不出必须返回 NULL，才能区分"公司名判定"和"按岗位推断"。"""
    assert conn2.execute(
        "SELECT fn_company_domain('随便一个名字') AS d").fetchone()["d"] is None


@pytest.mark.parametrize("category,expected", [
    ("后端开发", "信息技术"),
    ("测试", "信息技术"),
    ("销售/市场", "企业服务"),
    ("普工/操作", "制造工业"),
    ("物流/仓储", "交通物流"),
    ("传媒/内容", "传媒文化"),
    ("产品研发(非软件)", "制造工业"),
])
def test_category_fallback(conn2, category, expected):
    """公司名认不出时，按岗类反推。"""
    assert dom(conn2, "随便一个名字", category) == expected


def test_unknown_category_falls_to_other(conn2):
    assert dom(conn2, "随便一个名字", None) == "其他行业"
