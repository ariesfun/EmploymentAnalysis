"""BOSS 适配器测试（全离线）。

重点验证三件事：
1. 解析器只取岗位侧字段，**HR 姓名/活跃状态即便出现在 HTML 里也不进结果**；
2. robots.txt 明确禁止 `?query=` / `?city=` 时，fetch 直接拒绝（不发请求）；
3. 返回 JS 空壳页时抛 CaptchaDetected，而不是静默返回 0 条。
"""
import json

import httpx
import pytest

from jobmvp.adapter import CaptchaDetected, RawPage
from jobmvp.sources.boss import BossAdapter

# 含 HR 信息的卡片（.job-boss-info 里有姓名与活跃状态）
_CARD_HTML = """
<html><body>
<ul class="job-list-box">
  <li class="job-card-wrapper">
    <div class="job-card-body">
      <a class="job-card-left" href="/job_detail/abc123def.html?lid=1">
        <div class="job-title">
          <span class="job-name">Java开发工程师</span>
          <span class="job-area">北京·朝阳区</span>
        </div>
        <div class="job-info">
          <span class="salary">20-40K·14薪</span>
          <ul class="tag-list"><li>3-5年</li><li>本科</li></ul>
        </div>
      </a>
      <div class="job-card-right">
        <div class="company-info"><h3 class="company-name">某某科技有限公司</h3></div>
        <div class="job-boss-info">
          <h2 class="name">张女士</h2>
          <div class="boss-info-attr">招聘专员</div>
          <span class="boss-active-time">刚刚活跃</span>
        </div>
      </div>
    </div>
  </li>
  <li class="job-card-wrapper">
    <div class="job-card-body">
      <a class="job-card-left" href="/job_detail/xyz789.html">
        <div class="job-title">
          <span class="job-name">后端开发工程师</span>
          <span class="job-area">上海·浦东新区</span>
        </div>
        <div class="job-info"><span class="salary">15-25K</span></div>
      </a>
      <div class="job-card-right">
        <div class="company-info"><h3 class="company-name">另一家公司</h3></div>
      </div>
    </div>
  </li>
</ul>
</body></html>
"""

_ROBOTS_DENY = "User-agent: *\nDisallow: /*?query=*\nDisallow: *?city=*\n"
_ROBOTS_ALLOW = "User-agent: *\nAllow: /\n"


def _adapter(handler=None, **kw):
    handler = handler or (lambda req: httpx.Response(200, text=""))
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return BossAdapter(client, "https://www.zhipin.com", **kw)


def _page(body: str) -> RawPage:
    return RawPage(url="https://www.zhipin.com/web/geek/jobs?query=Java", status=200, body=body)


# ---------------------------------------------------------------- 解析
def test_parse_extracts_job_side_fields():
    items = _adapter().parse(_page(_CARD_HTML))
    assert len(items) == 2

    first = items[0]
    assert first["source_job_id"] == "abc123def"
    assert first["title_raw"] == "Java开发工程师"
    assert first["location_raw"] == "北京·朝阳区"
    assert first["salary_raw"] == "20-40K·14薪"
    assert first["company_name"] == "某某科技有限公司"
    assert first["url"].startswith("https://www.zhipin.com/job_detail/")

    assert items[1]["source_job_id"] == "xyz789"
    assert items[1]["salary_raw"] == "15-25K"


def test_parse_never_emits_hr_info():
    """HR 姓名/职位/活跃状态在页面上，但必须一个字节都不进结果。"""
    blob = json.dumps(_adapter().parse(_page(_CARD_HTML)), ensure_ascii=False)
    for leaked in ("张女士", "招聘专员", "刚刚活跃", "boss"):
        assert leaked not in blob


def test_parse_raises_when_no_cards():
    with pytest.raises(ValueError):
        _adapter().parse(_page("<html><body>安全验证</body></html>"))


# ---------------------------------------------------------------- 抓取闸门
def test_robots_disallows_query_url():
    """BOSS 的 robots.txt 明确 Disallow /*?query=*，必须直接拒绝。"""
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=_ROBOTS_DENY)
        return httpx.Response(200, text=_CARD_HTML)

    with pytest.raises(PermissionError):
        _adapter(handler).fetch("https://www.zhipin.com/web/geek/jobs?query=Java&city=101010100")


def test_js_shell_raises_captcha():
    """返回 SPA 空壳（browser-check）时抛 CaptchaDetected，而不是当作 0 条。"""
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=_ROBOTS_ALLOW)
        return httpx.Response(200, text='<html><body>加载中，请稍候'
                                        '<script src="/sdk/browser-check-v2.js"></script></body></html>')

    with pytest.raises(CaptchaDetected):
        _adapter(handler).fetch("https://www.zhipin.com/web/geek/jobs?query=Java")


def test_security_check_page_raises_captcha():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=_ROBOTS_ALLOW)
        return httpx.Response(200, text="<html><body>请完成安全验证</body></html>")

    with pytest.raises(CaptchaDetected):
        _adapter(handler).fetch("https://www.zhipin.com/web/geek/jobs?query=Java")


def test_discover_builds_paged_urls():
    urls = list(_adapter().discover(3))
    assert len(urls) == 3
    assert "query=Java" in urls[0] and "page=1" in urls[0]
    assert "page=3" in urls[-1]
