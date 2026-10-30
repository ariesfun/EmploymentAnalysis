"""中国公共招聘网（job.mohrss.gov.cn）适配器 —— A 级来源。

站点性质：人社部主办的公共就业服务平台，公开列表页，无需登录、无验证码。
数据形态：列表页 HTML 内嵌 `<input id="findjoblist" value="{JSON}">`，每页 20 条。

合规要点（对齐 jobmvp 的十条硬约束）：
- 只读列表页，不进入详情页，不做任何反爬对抗；
- 源站列表含 `aae004`（联系人）/`aae005`（联系电话）/`aae013`（邮箱），
  本适配器**根本不读取**这些键，从源头杜绝 PII 进入管道；
- 频率与页数由 `source_config.min_interval_s / max_pages` 控制，不写死在代码里。
"""

from __future__ import annotations

import html as html_lib
import json
import re
from urllib.parse import urlencode

from pathlib import Path

from ..adapter import HttpAdapter, RawPage

# 区划码前 4 位 -> 地级市（由 tools/gen_regions.py 生成）
_PREFECTURE: dict[str, str] = json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "regions.json")
    .read_text(encoding="utf-8")
)

_LIST_URL = "http://job.mohrss.gov.cn/cjobs/jobinfolist/listJobinfolist"
_DETAIL_URL = "http://job.mohrss.gov.cn/cjobs/jobinfolist/cb21/showgw?id={job_id}"

# 只读取这些键；PII 键（aae004/aae005/aae013）不在其中，天然不会被采集
_KEYS = ("acb200", "aca112", "aab004", "aab001", "aab301", "aab302", "acb202",
         "aca111_", "acb22a", "acb240", "acb241", "acb242", "s_aae395", "ace760")

_JSON_RE = re.compile(r'<input[^>]*id="findjoblist"[^>]*value="([^"]*)"', re.S | re.I)
_DISTRICT_SUFFIX = ("区", "县", "旗")
_CITY_SUFFIX = ("市", "自治州", "地区", "盟")


def _norm_city(name: str) -> str:
    """'长春市' -> '长春'；自治州/地区/盟保持原样（避免歧义）。"""
    if not name:
        return ""
    if name.endswith("市") and len(name) > 2:
        return name[:-1]
    return name


def area_kind(area_short: str) -> tuple[str, str]:
    """判断 aab302 的粒度，返回 (kind, value)。

    kind: city（地级市）/ district（区县）/ province（省级）/ unknown
    """
    s = (area_short or "").strip()
    if not s:
        return "unknown", ""
    if s.endswith(_DISTRICT_SUFFIX):
        return "district", s
    if s.endswith(_CITY_SUFFIX):
        return "city", _norm_city(s)
    if s.endswith(("省", "自治区")):
        return "province", s
    return "unknown", s


class MohrssAdapter(HttpAdapter):
    source_id = "mohrss"
    # 该站无验证码机制；保留空元组，若将来出现再补特征串
    captcha_markers: tuple[str, ...] = ("请完成安全验证", "访问验证")

    def __init__(self, client, base_url: str = "http://job.mohrss.gov.cn",
                 keyword: str = "", keywords: list[str] | None = None):
        super().__init__(client, base_url)
        self.keyword = keyword
        # 多关键词轮转：一次运行内依次覆盖多个检索词，避免只抓单一方向
        kws = [k.strip() for k in (keywords or []) if k and k.strip()]
        if not kws and keyword.strip():
            kws = [keyword.strip()]
        self.keywords = kws

    # ------------------------------------------------------------ 发现
    def discover(self, max_pages: int):
        """按关键词轮转产出列表页 URL。

        源站的 textfield 检索会匹配岗位描述，相关性一般，但能显著提高目标岗类的密度；
        不传关键词时退回全站顺序（样本会偏向少数发布机构）。
        """
        total = max(1, int(max_pages))
        if not self.keywords:
            for page_no in range(1, total + 1):
                yield self._list_url("", page_no)
            return
        n = len(self.keywords)
        for i in range(total):
            kw = self.keywords[i % n]
            page_no = i // n + 1
            yield self._list_url(kw, page_no)

    @staticmethod
    def _list_url(keyword: str, page_no: int) -> str:
        # 必须走 urlencode：中文关键词不编码会被服务端忽略，返回一堆无关岗位
        params = {"pageNo": page_no, "pagecount": "", "orderType": "score", "s_acb241": "0"}
        if keyword:
            params["textfield"] = keyword
        return f"{_LIST_URL}?{urlencode(params)}"

    # ------------------------------------------------------------ 解析
    def parse(self, page: RawPage):
        """返回列表；单条缺关键字段时交由 runner 记入 parse_error（不在此静默丢弃）。"""
        m = _JSON_RE.search(page.body)
        if not m:
            raise ValueError("列表页未找到 findjoblist 数据块（可能改版或被拦截）")
        try:
            rows = json.loads(html_lib.unescape(m.group(1)))
        except json.JSONDecodeError as exc:
            raise ValueError(f"findjoblist JSON 解析失败: {exc}") from exc
        if not isinstance(rows, list):
            raise ValueError("findjoblist 不是数组")

        # 第一遍：从「市级」行学习 行政区划前 4 位 -> 城市名
        # 用于把只给了区县的岗位归并到所属城市（源站不给区县→城市映射表）
        code2city: dict[str, str] = {}
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            kind, val = area_kind(raw.get("aab302"))
            code = str(raw.get("aab301") or "")
            if kind == "city" and val and len(code) >= 4:
                code2city.setdefault(code[:4], val)

        out = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            r = {k: raw.get(k) for k in _KEYS}
            job_id = str(r.get("acb200") or "").strip()
            if not job_id:
                continue

            lo, hi = r.get("acb241"), r.get("acb242")
            try:
                lo_n = float(lo) if lo not in (None, "", 0) else None
                hi_n = float(hi) if hi not in (None, "", 0) else None
            except (TypeError, ValueError):
                lo_n = hi_n = None

            if lo_n and hi_n and hi_n > lo_n:
                salary_raw = f"{lo_n:g}-{hi_n:g}元/月"
            elif lo_n:
                salary_raw = f"{lo_n:g}元以上/月"
            else:
                salary_raw = "面议"

            # 地区：区划码优先（跨页有效），源站地区名兜底。
            # 不使用 acb202（单位注册地址，常与工作地不符）。
            kind, val = area_kind(r.get("aab302"))
            code = str(r.get("aab301") or "")
            city, district = "", ""

            if len(code) >= 4 and not code.endswith("0000"):   # 非省级码
                city = _norm_city(_PREFECTURE.get(code[:4], ""))

            if kind == "city":
                city = city or val
            elif kind == "district":
                district = val

            if not city and code:                              # 同页兜底
                city = code2city.get(code[:4], "")

            if city and district:
                location_raw = f"{city}·{district}"
            else:
                # 城市未解析出来时不退化成「把区县当城市」，留空更诚实
                location_raw = city or ""

            out.append({
                "source_job_id": job_id,
                "url": (r.get("ace760") or "").strip() or _DETAIL_URL.format(job_id=job_id),
                "title_raw": (r.get("aca112") or "").strip(),
                "location_raw": location_raw,
                "salary_raw": salary_raw,
                "experience_raw": None,       # 列表页不提供，详情页才有（MVP 不抓详情）
                "edu": None,
                "company_name": (r.get("aab004") or "").strip(),
                "description": (r.get("acb22a") or "").strip(),
                "posted_at": (r.get("s_aae395") or "")[:10] or None,
                # 源站自带行政区划码（aab301），比查字典更准，直接透传
                "region_code": code or None,
                # 以下为字典预热用的辅助键，sanitize() 会按白名单裁掉，不会入库
                "_city_code": code,
                "_city": city,
            })
        return out
