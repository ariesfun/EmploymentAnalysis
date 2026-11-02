"""采集核心的纯函数测试（不连库、不发请求）。"""
from jobmvp import boss_collect


def test_build_combos_cross_product():
    plan = {
        "keywords": ["开发", " 前端 ", "", "测试"],
        "cities": [{"code": "101110100", "name": "西安"},
                   {"code": "101270100", "name": "成都"}],
        "pages_per_combo": 3,
    }
    combos, pages = boss_collect.build_combos(plan)
    # 空关键词被过滤 -> 3 词 × 2 城 = 6 个组合
    assert len(combos) == 6
    assert pages == 3
    assert combos[0] == ("开发", "101110100", "西安")
    assert combos[-1] == ("测试", "101270100", "成都")
    assert ("前端", "101110100", "西安") in combos          # 前后空格被 strip


def test_build_combos_pages_clamped():
    plan = {"keywords": ["开发"], "cities": [{"code": "101110100", "name": "西安"}],
            "pages_per_combo": 99}
    _, pages = boss_collect.build_combos(plan)
    assert pages == boss_collect.MAX_PAGES                  # 上限保护 10 页

    plan["pages_per_combo"] = 0
    _, pages = boss_collect.build_combos(plan)
    assert pages == 1                                       # 下限 1 页


def test_build_combos_city_name_fallback():
    """城市名缺失时用 CITY_NAMES 兜底，不把城市码当名字显示。"""
    combos, _ = boss_collect.build_combos(
        {"keywords": ["开发"], "cities": [{"code": "101010100"}], "pages_per_combo": 1})
    assert combos[0] == ("开发", "101010100", "北京")


def test_risk_codes_cover_known_blocks():
    for code in (35, 36, 37, 401, 403):
        assert code in boss_collect.RISK_CODES
    assert 0 not in boss_collect.RISK_CODES                 # 0 是正常，绝不能当风控
