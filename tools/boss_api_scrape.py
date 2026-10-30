"""BOSS 主动调 API 采集（借鉴 eatmoreduck/boss-zhipin-scraper 的做法）。

原理
----
BOSS 前端的字体反爬只在前端渲染层；它自己的前端也要拿薪资，走内部 API
`/wapi/zpgeek/search/joblist.json`，返回 JSON 里的 `salaryDesc` 是**明文**
（如 `30-60K·15薪`）。所以在**已登录页面上下文**里 fetch 该 API（带 cookie），
就能拿到明文数据，且支持分页与筛选——比"旁听页面当前页"产量高得多。

前置
----
Chrome 9223 常驻且已登录 BOSS（tools/start_boss_chrome.bat）。

用法
----
    python tools/boss_api_scrape.py --keyword 开发 --city 101110100 --pages 3
    python tools/boss_api_scrape.py --keyword C++ --city 101270100 --pages 2 --no-ingest

反爬
----
翻页随机延迟 12-22 秒（模拟真人节奏），单次页数有上限保护。仅个人研究用途。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# playwright 连 127.0.0.1 不应走代理
for _k in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_k, None)

from playwright.sync_api import sync_playwright  # noqa: E402

from jobmvp import store  # noqa: E402
from jobmvp.adapter import sanitize  # noqa: E402
from jobmvp.runner import load_dicts, normalize_item  # noqa: E402

CDP = os.environ.get("BOSS_CDP_URL", "http://127.0.0.1:9223")
DSN = os.environ.get("JOBMVP_DSN", "postgresql://mvp:mvp@127.0.0.1:5432/jobmvp")
API = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
MAX_PAGES = 10          # 单次上限保护（30 条/页 × 10 = 300 条）


def fetch_page(page, keyword: str, city: str, page_no: int, page_size: int = 30) -> dict:
    """调 joblist API（复用页面 cookie）。

    用 page.request 而不是 page.evaluate(fetch)：
    前者走页面所属 context 的 cookie，不依赖页面 DOM/执行上下文，
    因此页面导航（SPA 跳转、browser-check）不会导致 "Execution context destroyed"。
    """
    url = (f"{API}?scene=1&query={keyword}&city={city}"
           f"&page={page_no}&pageSize={page_size}")
    resp = page.request.get(url)
    return resp.json()


def ingest(jobs: list[dict]) -> dict:
    items = []
    for j in jobs:
        jid = j.get("encryptJobId") or ""
        if not jid:
            continue
        c = j.get("cityName") or ""
        d = j.get("areaDistrict") or ""
        items.append({
            "source_job_id": str(jid),
            "url": f"https://www.zhipin.com/job_detail/{jid}.html",
            "title_raw": j.get("jobName") or "",
            "location_raw": f"{c}·{d}" if d else c,
            "salary_raw": j.get("salaryDesc") or "",
            "experience_raw": j.get("jobExperience"),
            "edu": j.get("jobDegree"),
            "company_name": j.get("brandName") or "",
            "description": None,
            "posted_at": None,
        })
    conn = store.connect(DSN)
    wl = conn.execute(
        "SELECT field_whitelist FROM source_config WHERE source_id='boss'"
    ).fetchone()["field_whitelist"]
    matcher, rules, regions = load_dicts(conn)
    run_id = store.start_run(conn, "boss", "cdp")
    stats = {"new": 0, "changed": 0, "reopened": 0, "seen": 0}
    for it in items:
        rec = normalize_item(conn, sanitize(it, wl), matcher, rules, regions, raw_path="cdp")
        ev = store.upsert_job(conn, run_id, "boss", rec)
        stats[ev] = stats.get(ev, 0) + 1
    conn.commit()
    store.finish_run(conn, run_id, "success", None, fetched=len(jobs), parsed=len(items),
                     upserted=sum(stats.values()), parse_failed=0, closed=0)
    conn.commit()
    conn.close()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="BOSS 主动调 API 采集")
    ap.add_argument("--keyword", default="开发")
    ap.add_argument("--city", default="101110100", help="BOSS 城市码，西安=101110100")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--page-size", type=int, default=30)
    ap.add_argument("--no-ingest", action="store_true", help="只抓不写库")
    ap.add_argument("--min-delay", type=float, default=12)
    ap.add_argument("--max-delay", type=float, default=22)
    args = ap.parse_args()

    pages = max(1, min(args.pages, MAX_PAGES))
    total = 0
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(CDP)
        page = b.contexts[0].pages[0]
        # API 只需 zhipin.com 的 cookie，不必在搜索页；先导航到首页稳定上下文，
        # 避免搜索页 SPA 导航导致 "Execution context was destroyed"
        try:
            page.goto("https://www.zhipin.com/", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(3_000)
        except Exception as e:  # noqa: BLE001
            print("导航首页失败（继续尝试）:", type(e).__name__, str(e)[:60])
        for pn in range(1, pages + 1):
            print(f"\n=== 第 {pn} 页（keyword={args.keyword} city={args.city}）===")
            try:
                data = fetch_page(page, args.keyword, args.city, pn, args.page_size)
            except Exception as e:  # noqa: BLE001
                print("  请求失败:", type(e).__name__, str(e)[:90])
                break
            code = data.get("code")
            jobs = (data.get("zpData") or {}).get("jobList") or []
            print(f"  code={code} 岗位数={len(jobs)}")
            if not jobs:
                print("  无更多数据，停止")
                break
            if not args.no_ingest:
                print("  入库:", ingest(jobs))
            total += len(jobs)
            if pn < pages:
                delay = random.uniform(args.min_delay, args.max_delay)
                print(f"  随机延迟 {delay:.1f}s ...")
                time.sleep(delay)
    print(f"\n完成，共 {total} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
