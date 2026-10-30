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

import logging  # noqa: E402

# ---------------------------------------------------------------- 采集日志
# 采集是独立进程，print 只到终端；这里同时写 logs/scrape.log，
# 让看板「运行日志（实时）」也能看到采集过程的关键执行信息。
_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_SCRAPE_LOG = _LOG_DIR / "scrape.log"

_fmt = logging.Formatter("%(asctime)s %(levelname)-5s scrape: %(message)s", "%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("scrape")
if not logger.handlers:
    _fh = logging.FileHandler(_SCRAPE_LOG, encoding="utf-8")
    _fh.setFormatter(_fmt)
    _sh = logging.StreamHandler()
    _sh.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_fh)
    logger.addHandler(_sh)
    logger.setLevel(logging.INFO)
    logger.propagate = False

from playwright.sync_api import sync_playwright  # noqa: E402

from jobmvp import store  # noqa: E402
from jobmvp.adapter import sanitize  # noqa: E402
from jobmvp.runner import load_dicts, normalize_item  # noqa: E402

CDP = os.environ.get("BOSS_CDP_URL", "http://127.0.0.1:9223")
DSN = os.environ.get("JOBMVP_DSN", "postgresql://mvp:mvp@127.0.0.1:5432/jobmvp")
API = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
MAX_PAGES = 10          # 单次上限保护（30 条/页 × 10 = 300 条）

CITY_NAMES = {
    "101010100": "北京", "101020100": "上海", "101270100": "成都",
    "101040100": "重庆", "101110100": "西安", "101280100": "广州",
    "101280600": "深圳", "101210100": "杭州",
}


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


def ingest(jobs: list[dict]) -> tuple[dict, int]:
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
    return stats, run_id


def log_step(conn, run_id, keyword, city_code, city_name, page_no,
             job_count, code, elapsed_ms, status, error=None) -> None:
    """写一条采集步骤日志。失败不影响主流程（日志本身不该拖垮采集）。"""
    try:
        conn.execute(
            """INSERT INTO scrape_step_log
                 (run_id, source_id, keyword, city_code, city_name, page, job_count,
                  code, elapsed_ms, status, error)
               VALUES (%s,'boss',%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (run_id, keyword, city_code, city_name, page_no, job_count,
             code, elapsed_ms, status, error),
        )
        conn.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("写采集日志失败: %s %s", type(e).__name__, str(e)[:60])


def main() -> int:
    ap = argparse.ArgumentParser(description="BOSS 主动调 API 采集")
    ap.add_argument("--plan", action="store_true",
                    help="从 scrape_plan 表读取关键词/城市/页数（看板「采集配置」保存的）")
    ap.add_argument("--keyword", default="开发")
    ap.add_argument("--city", default="101110100", help="BOSS 城市码，西安=101110100")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--page-size", type=int, default=30)
    ap.add_argument("--no-ingest", action="store_true", help="只抓不写库")
    ap.add_argument("--min-delay", type=float, default=12)
    ap.add_argument("--max-delay", type=float, default=22)
    args = ap.parse_args()

    # 生成采集组合（关键词 × 城市 × 页）
    if args.plan:
        conn = store.connect(DSN)
        plan = conn.execute("SELECT * FROM scrape_plan WHERE source_id='boss'").fetchone()
        conn.close()
        if not plan or not plan["enabled"]:
            logger.warning("采集计划未启用或无配置，退出")
            return 1
        keywords = list(plan["keywords"] or [])
        cities = list(plan["cities"] or [])
        pages = max(1, min(int(plan["pages_per_combo"] or 2), MAX_PAGES))
        combos = [(kw, c["code"], c["name"]) for kw in keywords for c in cities]
        logger.info(f"采集计划：{len(keywords)} 词 × {len(cities)} 城 × {pages} 页 "
                    f"= {len(combos) * pages} 页请求")
    else:
        combos = [(args.keyword, args.city, CITY_NAMES.get(args.city, args.city))]
        pages = max(1, min(args.pages, MAX_PAGES))

    total = 0
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(CDP)
        page = b.contexts[0].pages[0]
        try:
            page.goto("https://www.zhipin.com/", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(3_000)
        except Exception as e:  # noqa: BLE001
            logger.warning("导航首页失败（继续尝试）: %s %s", type(e).__name__, str(e)[:60])

        log_conn = store.connect(DSN)      # 专用于写步骤日志，与 ingest 的连接分开
        for kw, city_code, city_name in combos:
            for pn in range(1, pages + 1):
                logger.info(f"--- {city_name} / {kw} 第 {pn} 页 ---")
                t0 = time.time()
                try:
                    data = fetch_page(page, kw, city_code, pn, args.page_size)
                except Exception as e:  # noqa: BLE001
                    elapsed = int((time.time() - t0) * 1000)
                    logger.error("请求失败: %s %s", type(e).__name__, str(e)[:90])
                    log_step(log_conn, None, kw, city_code, city_name, pn, 0, None,
                             elapsed, "error", f"{type(e).__name__}: {str(e)[:200]}")
                    break
                elapsed = int((time.time() - t0) * 1000)
                code = data.get("code")
                jobs = (data.get("zpData") or {}).get("jobList") or []
                logger.info(f"code={code} 岗位数={len(jobs)} 耗时={elapsed}ms")

                run_id = None
                if jobs and not args.no_ingest:
                    stats, run_id = ingest(jobs)
                    logger.info(f"入库: {stats}")

                log_step(log_conn, run_id, kw, city_code, city_name, pn, len(jobs), code,
                         elapsed, "ok" if jobs else "empty",
                         None if code in (0, None) else f"接口 code={code}")

                if not jobs:
                    logger.info("无更多数据，结束该组合")
                    break
                total += len(jobs)
                if pn < pages:
                    delay = random.uniform(args.min_delay, args.max_delay)
                    logger.info(f"随机延迟 {delay:.1f}s")
                    time.sleep(delay)
        log_conn.close()
    logger.info(f"采集完成，共 {total} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
