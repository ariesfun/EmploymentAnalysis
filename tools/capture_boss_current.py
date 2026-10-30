"""采集 BOSS 当前页面（已登录 Chrome）的岗位并入库。

背景
----
BOSS 的城市由登录态决定，城市选择弹窗在 CDP 自动化下不稳定
（元素 detached、页面导航、结构变化），无法可靠自动切换城市。
因此本工具只采集「浏览器当前所在城市」，城市切换由人工在浏览器里完成。

用法
----
1. 在 Chrome(9223) 里手动切到目标城市（如成都）
2. python tools/capture_boss_current.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# playwright 连 127.0.0.1 不应走代理，否则会 502
for _k in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_k, None)

from playwright.sync_api import sync_playwright  # noqa: E402

from jobmvp import store  # noqa: E402
from jobmvp.adapter import sanitize  # noqa: E402
from jobmvp.runner import load_dicts, normalize_item  # noqa: E402

CDP = os.environ.get("BOSS_CDP_URL", "http://127.0.0.1:9223")
DSN = os.environ.get("JOBMVP_DSN", "postgresql://mvp:mvp@127.0.0.1:5432/jobmvp")


def main() -> int:
    payloads: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(CDP)
        page = b.contexts[0].pages[0]

        def on_resp(r):
            if "joblist.json" in r.url:
                try:
                    payloads.append(r.text())
                except Exception:  # noqa: BLE001
                    pass

        page.on("response", on_resp)
        for _ in range(3):
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(1200)
        page.wait_for_timeout(2500)
        url = page.url

    if not payloads:
        print("未捕获 joblist。请确认：Chrome 已登录、页面在职位搜索页。")
        return 2

    data = json.loads(payloads[0])           # 第一页（最新）
    jobs = (data.get("zpData") or {}).get("jobList") or []
    if not jobs:
        print("joblist 为空，可能被风控或未登录")
        return 3

    print("页面:", url[:90])
    print("捕获岗位:", len(jobs), "| 城市:", Counter(j.get("cityName") for j in jobs).most_common(3))

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
    print("入库:", stats)

    print("\n=== BOSS 城市分布 ===")
    for r in conn.execute(
        "SELECT city, coalesce(district,'(无区)') d, count(*) n FROM job "
        "WHERE source_id='boss' GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10"
    ):
        print(f"  {r['city']}·{r['d']}: {r['n']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
