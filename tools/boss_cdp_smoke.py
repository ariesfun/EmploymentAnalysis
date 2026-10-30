"""BOSS 直聘 CDP 最小验证（只读自检：不写库、不落文件、不改数据）。

目的
----
在本机确认「CDP 被动旁听」这条路线能否拿到**明文**薪资（`salaryDesc`），
用于判断是否值得把 BossAdapter 升级成 cdp 模式。

前置条件（必须由人手动完成）
--------------------------
1. 用**独立 profile** 启动 Chrome 并开调试端口：
   chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\\temp\\boss-profile
2. 在这个 Chrome 里**手动登录** BOSS（扫码/账号均可）。
3. 保持该 Chrome 常驻，再运行本脚本。

用法
----
    python tools/boss_cdp_smoke.py --keyword Java --city 101010100

判定（任一不满足即 FAIL）
------------------------
- 返回岗位数 >= 20
- 六项字段（岗位名/公司/薪资/城市/经验/学历）非空率 >= 90%
- salaryDesc 匹配 ^\\d+-\\d+K 的比例 >= 90%（证明拿到的是明文，不是字体加密乱码）

合规
----
个人学习研究用途；低频、只读、不采 HR 个人信息、遇验证码立即停止、不做任何绕过。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from urllib.parse import quote

CDP_DEFAULT = "http://127.0.0.1:9223"   # 9222 被 WorkBuddy 自带 Chrome 占用，改用 9223
SALARY_RE = re.compile(r"^\d+-\d+K")
JOBLIST_MARKERS = ("joblist.json", "search/joblist")


def check_cdp(cdp: str) -> tuple[bool, str]:
    try:
        import httpx
        r = httpx.get(cdp.rstrip("/") + "/json/version", timeout=3)
        if r.status_code == 200:
            return True, r.json().get("Browser", "?")
        return False, f"HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description="BOSS CDP 最小验证（只读）")
    ap.add_argument("--keyword", default="Java")
    ap.add_argument("--city", default="101010100", help="BOSS 城市码，默认北京")
    ap.add_argument("--cdp", default=CDP_DEFAULT)
    ap.add_argument("--wait", type=int, default=10, help="页面加载后等待秒数")
    args = ap.parse_args()

    ok, info = check_cdp(args.cdp)
    print(f"[1] CDP 可达: {ok} ({info})")
    if not ok:
        print("\n  请先用独立 profile 启动 Chrome（并手动登录 BOSS）：")
        print('  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
              '--remote-debugging-port=9222 --user-data-dir=C:\\temp\\boss-profile')
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[FAIL] 未安装 playwright，先执行: pip install playwright && playwright install chrome")
        return 2

    url = (f"https://www.zhipin.com/web/geek/jobs"
           f"?query={quote(args.keyword)}&city={args.city}&page=1")
    responses: list = []
    body_text = ""

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(args.cdp)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        # Chrome 138 的 CDP 不支持 Target.createTarget，复用已打开的页面
        reused = bool(ctx.pages)
        page = ctx.pages[0] if reused else ctx.new_page()
        page.on("response", lambda r: responses.append(r) if any(m in r.url for m in JOBLIST_MARKERS) else None)
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(args.wait * 1000)
        title = page.title()
        body_text = page.inner_text("body")[:160].replace("\n", " ")
        # 加载完成后统一取 body（避免在回调里阻塞）
        payloads: list[str] = []
        for r in responses:
            try:
                payloads.append(r.text())
            except Exception:  # noqa: BLE001
                pass
        if not reused:                 # 复用了用户已开的页面就不关，避免干扰
            page.close()

    print(f"[2] 页面标题: {title}")
    print(f"[3] 捕获 joblist 响应: {len(responses)} 个，可用 body: {len(payloads)} 个")

    if not payloads:
        if any(k in body_text for k in ("安全验证", "请完成验证", "验证码")):
            print("    [FAIL] 出现安全验证页（风控拦截）。立即停止，不做任何绕过。")
        else:
            print("    [FAIL] 未捕获到 joblist.json。可能：未登录 / 需手动触发搜索 / 站点改版。")
            print(f"    页面片段: {body_text}")
        return 3

    try:
        data = json.loads(payloads[-1])
    except Exception as e:  # noqa: BLE001
        print(f"    [FAIL] 响应不是 JSON: {e}")
        print(f"    片段: {payloads[-1][:200]}")
        return 4

    zp = data.get("zpData") or {}
    jobs = zp.get("jobList") or []
    print(f"[4] code={data.get('code')} message={data.get('message')!r} 岗位数={len(jobs)}")

    if not jobs:
        print("    [FAIL] 返回 0 条。可能是风控（code 9/31/37）、未登录或筛选过窄。")
        print(f"    zpData keys: {list(zp.keys())[:10]}")
        return 5

    def g(j: dict, *keys):
        for k in keys:
            v = j.get(k)
            if v not in (None, "", []):
                return v
        return None

    six_ok = 0
    salary_plain = 0
    samples = []
    for j in jobs:
        title_ = g(j, "jobName")
        comp = g(j, "brandName", "companyName")
        sal = g(j, "salaryDesc")
        city = g(j, "cityName")
        exp = g(j, "jobExperience")
        deg = g(j, "jobDegree")
        if all([title_, comp, sal, city, exp, deg]):
            six_ok += 1
        if sal and SALARY_RE.match(sal):
            salary_plain += 1
        if len(samples) < 5:
            samples.append((title_, sal, comp, city, exp, deg))

    n = len(jobs)
    rate = six_ok / n * 100
    sp = salary_plain / n * 100
    print(f"[5] 六项字段非空率: {rate:.0f}% ({six_ok}/{n})")
    print(f"[6] salaryDesc 明文(^\\d+-\\d+K): {sp:.0f}% ({salary_plain}/{n})")
    print("    样本（岗位名 / 薪资 / 公司 / 城市 / 经验 / 学历）:")
    for s in samples:
        print("      ", s)

    passed = n >= 20 and rate >= 90 and sp >= 90
    print(f"\n=== 判定: {'PASS' if passed else 'FAIL'} ===")
    if passed:
        print("CDP 旁听可用，可把 BossAdapter 升级为 cdp 模式。")
    else:
        print("未达标：先别扩大采集，检查是否登录、是否被风控、字段结构是否改版。")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
