import pytest
from jobmvp.normalize import *

@pytest.mark.parametrize("raw,unit,lo,hi,months,ok", [
    ("30-35K", "month", 30, 35, None, True),
    ("20-40K·15薪", "month", 20, 40, 15, True),
    ("20-40k", "month", 20, 40, None, True),
    ("1.5-2万", "month", 15, 20, None, True),
    ("1.5-2万·13薪", "month", 15, 20, 13, True),
    ("8千-1.2万", "month", 8, 12, None, True),
    ("8000-12000元/月", "month", 8, 12, None, True),
    ("200-300元/天", "day", 200, 300, None, True),
    ("15-25元/时", "hour", 15, 25, None, True),
    ("35-30K", "month", 30, 35, None, True),
])
def test_salary_ok(raw, unit, lo, hi, months, ok):
    s = parse_salary(raw)
    assert (s.unit, s.min, s.max, s.months, s.ok) == (unit, lo, hi, months, ok)

@pytest.mark.parametrize("raw", ["面议", "", None, "薪资保密", "9999-99999K"])
def test_salary_bad(raw):
    assert parse_salary(raw).ok is False

def test_experience():
    assert parse_experience("3-5年") == (3, 5)
    assert parse_experience("10年以上") == (10, None)
    assert parse_experience("1年以内") == (0, 1)
    assert parse_experience("经验不限") == (0, 0)
    assert parse_experience("在校/应届") == (0, 0)
    assert parse_experience("abc") == (None, None)

def test_location():
    assert split_location("北京·海淀区·中关村") == ("北京", "海淀区")
    assert split_location("上海-浦东新区") == ("上海", "浦东新区")
    assert split_location("深圳") == ("深圳", None)
    assert split_location(None) == (None, None)

def test_skill_matcher():
    m = SkillMatcher({"C++": "C++", "Java": "Java", "JavaScript": "JavaScript", "Go": "Go",
                      "Python": "Python", "Spring Boot": "Spring Boot", "Spring": "Spring", "大数据": "大数据"})
    assert m.extract("熟悉C++/Qt开发") == ["C++"]
    assert m.extract("精通JavaScript") == ["JavaScript"]          # 不应命中 Java
    assert "Go" not in m.extract("有Google经验")                  # 不应命中 Go
    assert "Go" in m.extract("熟悉Go、Python3")
    assert "Python" in m.extract("Python3 开发")
    assert m.extract("Spring Boot 经验") == ["Spring Boot", "Spring"]  # 长词优先，Spring 也命中（可接受）
    assert m.extract("大数据平台") == ["大数据"]

def test_category():
    rules = [(r"c\+\+|嵌入式", "C++开发"), (r"算法|机器学习", "算法")]
    assert map_category("资深C++开发工程师", rules) == "C++开发"
    assert map_category("销售经理", rules) is None
