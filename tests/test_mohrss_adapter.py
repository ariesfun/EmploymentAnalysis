"""mohrss 适配器测试：解析、地区归并、PII 隔离、robots 与验证码行为。

全部离线（httpx.MockTransport），不触达真实站点。
"""
import html
import json

import httpx
import pytest

from jobmvp.adapter import CaptchaDetected, HttpAdapter, RawPage
from jobmvp.sources.mohrss import MohrssAdapter, area_kind

# 三条样本：市级 / 区县级 / 省级；均带 PII 字段（aae004 联系人、aae005 电话）
_ROWS = [
    {"acb200": 1001, "aca112": "Java开发工程师", "aab004": "甲公司", "aab001": 1,
     "aab301": "220100", "aab302": "长春市", "acb202": "吉林省长春市朝阳区",
     "aca111_": "信息和通信工程技术人员", "acb22a": "熟悉Spring、MySQL",
     "acb240": 2, "acb241": 8000, "acb242": 12000, "s_aae395": "2026-10-26",
     "ace760": "", "aae004": "张三", "aae005": "13800001111"},
    {"acb200": 1002, "aca112": "电工", "aab004": "乙公司", "aab001": 2,
     "aab301": "220105", "aab302": "二道区", "acb202": "吉林省长春市二道区",
     "aca111_": "电力工程技术人员", "acb22a": "有经验者优先",
     "acb240": 5, "acb241": 4000, "acb242": 6000, "s_aae395": "2026-10-25",
     "ace760": "", "aae004": "李四", "aae005": "13900002222"},
    {"acb200": 1003, "aca112": "数据分析师", "aab004": "丙公司", "aab001": 3,
     "aab301": "320000", "aab302": "江苏省", "acb202": "江苏省南京市玄武区",
     "aca111_": "统计人员", "acb22a": "熟悉SQL、Python",
     "acb240": 1, "acb241": 9000, "acb242": 0, "s_aae395": "2026-10-24",
     "ace760": "https://example.invalid/job/1003", "aae004": "王五", "aae005": "13700003333"},
]


def _page(rows=None) -> RawPage:
    payload = html.escape(json.dumps(_ROWS if rows is None else rows, ensure_ascii=False),
                          quote=True)
    body = f'<html><body><input type="hidden" id="findjoblist" value="{payload}"></body></html>'
    return RawPage(url="http://job.mohrss.gov.cn/x", status=200, body=body)


def _adapter(handler=None):
    handler = handler or (lambda req: httpx.Response(200, text=""))
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return MohrssAdapter(client, "http://job.mohrss.gov.cn")


# ---------------------------------------------------------------- 粒度判定
@pytest.mark.parametrize("raw,kind,value", [
    ("长春市", "city", "长春"),
    ("延边朝鲜族自治州", "city", "延边朝鲜族自治州"),
    ("二道区", "district", "二道区"),
    ("金坛区", "district", "金坛区"),
    ("江苏省", "province", "江苏省"),
    ("", "unknown", ""),
])
def test_area_kind(raw, kind, value):
    assert area_kind(raw) == (kind, value)


# ---------------------------------------------------------------- 解析
def test_parse_maps_fields_and_strips_pii():
    items = _adapter().parse(_page())
    assert len(items) == 3
    first = items[0]
    assert first["source_job_id"] == "1001"
    assert first["title_raw"] == "Java开发工程师"
    assert first["location_raw"] == "长春"
    assert first["salary_raw"] == "8000-12000元/月"
    assert first["region_code"] == "220100"
    # PII 绝不出现
    blob = json.dumps(items, ensure_ascii=False)
    for leaked in ("张三", "李四", "13800001111", "aae004", "aae005"):
        assert leaked not in blob


def test_parse_resolves_district_to_city():
    items = _adapter().parse(_page())
    assert items[1]["location_raw"] == "长春·二道区"      # 由同页 2201 学习到「长春」
    assert items[1]["region_code"] == "220105"


def test_parse_resolves_city_from_region_code_alone():
    """同页没有市级行时，也要能靠区划码前 4 位推出城市（regions.json）。"""
    only_district = [{**_ROWS[1], "aab302": "雁塔区", "aab301": "610113"}]
    items = _adapter().parse(_page(only_district))
    assert items[0]["location_raw"] == "西安·雁塔区"


def test_parse_municipality_district():
    """直辖市的区县码（1101xx）也要归到「北京」。"""
    rows = [{**_ROWS[0], "aab302": "海淀区", "aab301": "110108"}]
    assert _adapter().parse(_page(rows))[0]["location_raw"] == "北京·海淀区"


def test_parse_province_level_has_no_city():
    items = _adapter().parse(_page())
    assert items[2]["location_raw"] == ""                # 省级岗位不臆测城市
    assert items[2]["region_code"] == "320000"


def test_parse_single_sided_salary():
    items = _adapter().parse(_page())
    assert items[2]["salary_raw"] == "9000元以上/月"      # 只有下限
    items = _adapter().parse(_page([{**_ROWS[0], "acb241": 0, "acb242": 0}]))
    assert items[0]["salary_raw"] == "面议"


def test_parse_rejects_page_without_data_block():
    with pytest.raises(ValueError):
        _adapter().parse(RawPage(url="u", status=200, body="<html>改版了</html>"))


# ---------------------------------------------------------------- 抓取合规
def test_discover_respects_max_pages():
    urls = list(_adapter().discover(3))
    assert len(urls) == 3 and "pageNo=3" in urls[-1]


def test_robots_deny_blocks_fetch():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /cj")
        return httpx.Response(200, text="ok")
    with pytest.raises(PermissionError):
        _adapter(handler).fetch("http://job.mohrss.gov.cn/cjobs/jobinfolist/listJobinfolist")


def test_captcha_marker_halts():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, text="请完成安全验证")
    with pytest.raises(CaptchaDetected):
        _adapter(handler).fetch("http://job.mohrss.gov.cn/cjobs/jobinfolist/listJobinfolist")


def test_robots_unreachable_denies_all():
    with pytest.raises(PermissionError):
        _adapter(lambda req: httpx.Response(500, text="")).fetch(
            "http://job.mohrss.gov.cn/cjobs/jobinfolist/listJobinfolist")
