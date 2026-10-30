import httpx, pytest
from jobmvp.adapter import HttpAdapter, CaptchaDetected

class Demo(HttpAdapter):
    captcha_markers = ("安全验证",)
    def discover(self, max_pages): return [f"https://example.test/jobs?page={i}" for i in range(1, max_pages + 1)]
    def parse(self, page): return []

def make(handler):
    return Demo(httpx.Client(transport=httpx.MockTransport(handler)), "https://example.test")

def test_robots_disallow_blocks_fetch():
    def h(req):
        if req.url.path == "/robots.txt": return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        return httpx.Response(200, text="ok")
    a = make(h)
    assert a.fetch("https://example.test/jobs?page=1").status == 200
    with pytest.raises(PermissionError): a.fetch("https://example.test/private/x")

def test_robots_unreachable_means_deny_all():
    a = make(lambda req: httpx.Response(500, text="err"))
    with pytest.raises(PermissionError): a.fetch("https://example.test/jobs")

@pytest.mark.parametrize("resp", [httpx.Response(403, text="x"), httpx.Response(429, text="x"), httpx.Response(200, text="请完成安全验证")])
def test_captcha_or_block_halts(resp):
    def h(req):
        if req.url.path == "/robots.txt": return httpx.Response(200, text="User-agent: *\nAllow: /")
        return resp
    with pytest.raises(CaptchaDetected): make(h).fetch("https://example.test/jobs?page=1")
