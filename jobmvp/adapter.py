"""适配器接口与礼貌采集。合规元数据（tier/频率/白名单）来自 source_config，不写死在代码里。"""
from __future__ import annotations
import random, time, urllib.robotparser
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable
from urllib.parse import urlsplit

# 解析器出口字段全集；其余字段一律丢弃（白名单是 source_config.field_whitelist 的上限）
ALLOWED_FIELDS = {
    "source_job_id", "url", "title_raw", "location_raw", "salary_raw", "experience_raw", "edu",
    "company_name", "description", "posted_at", "region_code",
}
# 即便被误加入白名单也禁止入库的字段（PII）
PII_FIELDS = {"hr_name", "boss_name", "recruiter", "contact", "phone", "email", "wechat", "qq"}

class CaptchaDetected(Exception):
    """遇到验证码/安全验证：立即停止本次运行，不绕过。"""

@dataclass
class RawPage:
    url: str
    status: int
    body: str
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class Throttle:
    def __init__(self, min_interval_s: float, jitter: float = 0.3,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.min_interval, self.jitter, self._sleep, self._clock = min_interval_s, jitter, sleep, clock
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            need = self.min_interval * (1 + random.uniform(0, self.jitter)) - (now - self._last)
            if need > 0:
                self._sleep(need)
        self._last = self._clock()

def sanitize(item: dict, whitelist: Iterable[str]) -> dict:
    """按白名单裁剪字段；PII 字段无论如何都不保留。"""
    allow = (set(whitelist) & ALLOWED_FIELDS) - PII_FIELDS
    return {k: v for k, v in item.items() if k in allow}

class SourceAdapter(ABC):
    source_id: str

    @abstractmethod
    def discover(self, max_pages: int) -> Iterable[str]:
        """产出待抓取 URL（列表页/详情页）。"""

    @abstractmethod
    def fetch(self, url: str) -> RawPage:
        """抓取；遇验证码抛 CaptchaDetected；非 2xx 抛异常或返回带 status 的 RawPage。"""

    @abstractmethod
    def parse(self, page: RawPage) -> Iterable[dict]:
        """解析为字段字典；不得产出 PII；单条解析失败应抛异常由 runner 记入 parse_error，不得静默吞掉。"""

class HttpAdapter(SourceAdapter):
    """静态/接口类来源的基类：robots 校验 + 验证码特征检测。子类实现 discover/parse。"""
    user_agent = "JobMarketBot/0.1 (+contact: set-your-contact-url)"   # 须替换为真实可联系的标识
    captcha_markers: tuple[str, ...] = ()                               # 子类按来源配置

    def __init__(self, client, base_url: str):
        self.client, self.base_url = client, base_url
        self._robots = urllib.robotparser.RobotFileParser()
        r = client.get(base_url.rstrip("/") + "/robots.txt", headers={"User-Agent": self.user_agent})
        self._robots.parse(r.text.splitlines() if r.status_code == 200 else ["User-agent: *", "Disallow: /"])

    def fetch(self, url: str) -> RawPage:
        if not self._robots.can_fetch(self.user_agent, url):
            raise PermissionError(f"robots.txt 禁止抓取: {url}")
        r = self.client.get(url, headers={"User-Agent": self.user_agent})
        if r.status_code in (403, 429) or any(m in r.text for m in self.captcha_markers):
            raise CaptchaDetected(f"{r.status_code} {urlsplit(url).netloc}")
        return RawPage(url=url, status=r.status_code, body=r.text)
