"""BOSS 直聘适配器（**B 级来源**，默认关闭）。

合规定位
--------
按产品方案 2.2 的分级，商业招聘平台的公开页低频采集属 **B 级**：
- `source_config.tier='B'`、`enabled=false`；
- 启用必须填写 `approval_note`（法务意见/审批单号），库级 CHECK 兜底；
- 遇验证码/安全校验立即停止，不重试、不绕过、不做下架判定。

技术现状（2026-10 实测）
------------------------
1. 纯 HTTP 请求 `https://www.zhipin.com/web/geek/jobs?...` 返回的是 **JS 空壳**
   （`加载中，请稍候` + `browser-check-v2.js`），职位数据由 SPA 在通过浏览器
   指纹校验后才拉取，**HTTP 模式拿不到任何岗位**。
2. 真实 Chrome（Playwright）首次可过校验并渲染出页面框架，但结果区为空；
   再次请求即返回「安全验证」页。风控按 IP/会话累积。

因此本适配器有两种模式，都不做任何对抗：
- `http`（默认）：检测到空壳/校验页即抛 `CaptchaDetected`，run_log 记 `halted_captcha`；
- `browser`：用真实 Chrome 渲染（Playwright `channel="chrome"`），
  同样只做「渲染 + 读 DOM」，不注入脚本、不伪造指纹、不接代理池；
  若页面出现安全验证同样立即停止。

PII
---
BOSS 列表页含 HR 姓名、活跃状态、头像等。**本适配器根本不读取这些节点**：
只取职位名、地区、薪资、公司名、详情链接。理由有两条——
(1) 架构层 `PII_FIELDS` 是硬拦截，白名单也放不进来；
(2) 公开可见不等于可收集使用（PIPL 合法性基础），且 HR 姓名对市场分析无价值，
    留着只是徒增风险。
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..adapter import CaptchaDetected, HttpAdapter, RawPage

_LIST_URL = "https://www.zhipin.com/web/geek/jobs"
_DETAIL_PREFIX = "https://www.zhipin.com"

# 页面出现这些特征即视为「被风控拦截」——立即停止，不尝试任何绕过
_CHALLENGE_MARKERS = (
    "安全验证", "请完成验证", "验证码", "geetest", "browser-check",
    "访问过于频繁", "请稍后再试",
)

_JOB_ID_RE = re.compile(r"/job_detail/([0-9a-zA-Z_-]+)\.html")

# 结果卡片的候选选择器（站点改版时优先在这里加，而不是改解析逻辑）
_CARD_SELECTORS = ("li.job-card-wrapper", ".job-card-wrapper", "li.job-card-box")


def _text(node) -> str:
    return node.get_text(strip=True) if node else ""


class BossAdapter(HttpAdapter):
    source_id = "boss"
    captcha_markers = _CHALLENGE_MARKERS
    # 实测该站对非常规 UA 更敏感，这里用常见桌面 Chrome 标识（不伪装成爬虫友好 UA）
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )

    def __init__(self, client, base_url: str = "https://www.zhipin.com",
                 keyword: str = "Java", city_code: str = "101010100",
                 mode: str = "http", cdp_url: str = "http://127.0.0.1:9223"):
        super().__init__(client, base_url)
        self.keyword = keyword
        self.city_code = city_code
        self.mode = mode
        self.cdp_url = cdp_url

    # ------------------------------------------------------------ 发现
    def discover(self, max_pages: int):
        for page in range(1, max(1, int(max_pages)) + 1):
            qs = urlencode({"query": self.keyword, "city": self.city_code, "page": page})
            yield f"{_LIST_URL}?{qs}"

    # ------------------------------------------------------------ 抓取
    def fetch(self, url: str) -> RawPage:
        if self.mode == "cdp":
            return self._fetch_cdp(url)
        if self.mode == "browser":
            return self._fetch_browser(url)
        page = super().fetch(url)          # robots + 验证码特征由基类处理
        if self._is_shell(page.body):
            raise CaptchaDetected(
                "站点返回 JS 校验空壳（browser-check-v2），HTTP 模式无法获取职位；"
                "如需继续请评估 browser 模式并取得法务意见"
            )
        return page

    def _fetch_browser(self, url: str) -> RawPage:
        """真实 Chrome 渲染。只渲染、只读 DOM，不注入脚本、不伪造指纹。"""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            try:
                ctx = browser.new_context(locale="zh-CN",
                                          viewport={"width": 1366, "height": 900})
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(6_000)
                html = page.content()
            finally:
                browser.close()

        if any(m in html for m in _CHALLENGE_MARKERS):
            raise CaptchaDetected("渲染后出现安全验证页，已停止（不绕过）")
        return RawPage(url=url, status=200, body=html)

    @staticmethod
    def _is_shell(body: str) -> bool:
        """空壳页判定：既没有结果卡片，也没有正常内容。"""
        return ("加载中" in body or "browser-check" in body) and "job-card" not in body

    def _fetch_cdp(self, url: str) -> RawPage:
        """CDP 被动旁听：连本机已登录 Chrome，捕获页面自身发出的 joblist.json。

        不注入 XHR、不伪造指纹、不接代理池——只让真实浏览器自己发请求，我们旁听
        Network 响应。拿到接口层明文 salaryDesc（DOM 里是字体加密乱码）。
        需先手动启动 Chrome 并登录：--remote-debugging-port=9223。
        """
        from playwright.sync_api import sync_playwright

        payloads: list[str] = []
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(self.cdp_url)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            reused = bool(ctx.pages)
            page = ctx.pages[0] if reused else ctx.new_page()

            def on_resp(r):
                if "joblist.json" in r.url:
                    try:
                        payloads.append(r.text())   # 回调内即时取，reload 后 body 会失效
                    except Exception:  # noqa: BLE001
                        pass

            page.on("response", on_resp)
            if "geek/jobs" not in page.url:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            for _ in range(4):                 # 真实滚轮触发列表请求（不注入 JS）
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(1500)
            page.wait_for_timeout(3000)
            if not reused:
                page.close()

        if not payloads:
            raise CaptchaDetected("CDP 未捕获到 joblist（未登录 / 风控 / 改版），已停止")
        return RawPage(url=url, status=200, body=payloads[-1])

    # ------------------------------------------------------------ 解析
    def parse(self, page: RawPage):
        if page.body.lstrip().startswith("{"):     # CDP 模式返回的是 joblist JSON
            return self._parse_json(page.body)
        soup = BeautifulSoup(page.body, "lxml")

        cards = []
        for sel in _CARD_SELECTORS:
            cards = soup.select(sel)
            if cards:
                break
        if not cards:
            raise ValueError("页面中未找到岗位卡片（站点改版或被风控拦截）")

        out = []
        for card in cards:
            link = card.select_one("a.job-card-left") or card.select_one("a[href*='/job_detail/']")
            href = link.get("href", "") if link else ""
            m = _JOB_ID_RE.search(href)
            job_id = m.group(1) if m else ""

            title = _text(card.select_one(".job-name"))
            area = _text(card.select_one(".job-area"))
            salary = _text(card.select_one(".salary"))
            company = _text(card.select_one(".company-name"))

            # 注意：不读取 .job-boss-info / .info-public 等节点（HR 姓名/活跃状态）
            out.append({
                "source_job_id": job_id,
                "url": (_DETAIL_PREFIX + href) if href.startswith("/") else href,
                "title_raw": title,
                "location_raw": area,
                "salary_raw": salary,
                "experience_raw": None,     # 列表页未单独给出，详情页才有
                "edu": None,
                "company_name": company,
                "description": None,        # 列表页无 JD；MVP 不抓详情
                "posted_at": None,
            })
        return out

    @staticmethod
    def _parse_json(body: str):
        """解析 joblist.json 明文数据（CDP 模式）。只取岗位侧字段，不碰 HR。"""
        data = json.loads(body)
        jobs = (data.get("zpData") or {}).get("jobList") or []
        out = []
        for j in jobs:
            jid = j.get("encryptJobId") or j.get("jobId") or ""
            if not jid:
                continue
            city = j.get("cityName") or ""
            district = j.get("areaDistrict") or ""
            loc = f"{city}·{district}" if district else city
            out.append({
                "source_job_id": str(jid),
                "url": f"{_DETAIL_PREFIX}/job_detail/{jid}.html",
                "title_raw": j.get("jobName") or "",
                "location_raw": loc,
                "salary_raw": j.get("salaryDesc") or "",
                "experience_raw": j.get("jobExperience"),
                "edu": j.get("jobDegree"),
                "company_name": j.get("brandName") or j.get("companyName") or "",
                "description": None,
                "posted_at": None,
            })
        return out
