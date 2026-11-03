"""BOSS 主动调 API 采集 —— 项目内置采集能力。

抽出来的原因：原来采集逻辑只存在于 `tools/boss_api_scrape.py` 这个 CLI 里，
只能靠外部定时任务（宿主调度）来跑。控制台要「点按钮采集」「看实时进度」
就必须能在服务进程内直接调用，所以把核心逻辑搬到包里：

    jobmvp/boss_collect.py   核心（本文件）：连接 CDP → 调 joblist → 入库 → 写步骤日志
    tools/boss_api_scrape.py 只剩薄 CLI 壳（参数解析 + 退出码）
    console/app.py           控制台接口 + 后台线程 + 内置调度器

进度通过 `progress` 回调向外冒泡（每次翻页一次），控制台据此更新状态栏。

合规：只读列表接口，不采 HR 个人信息；遇风控码立即停，不重试、不绕过。
"""
from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path
from typing import Callable

from . import store
from .adapter import sanitize
from .runner import load_dicts, normalize_item

logger = logging.getLogger("scrape")

# ---------------------------------------------------------------- 常量

CDP = os.environ.get("BOSS_CDP_URL", "http://127.0.0.1:9223")
DSN = os.environ.get("JOBMVP_DSN", "postgresql://mvp:mvp@127.0.0.1:5432/jobmvp")
API = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
MAX_PAGES = 10          # 单次上限保护（30 条/页 × 10 = 300 条）

CITY_NAMES = {
    "101010100": "北京", "101020100": "上海", "101270100": "成都",
    "101040100": "重庆", "101110100": "西安", "101280100": "广州",
    "101280600": "深圳", "101210100": "杭州",
}

# 风控类返回码：一旦命中就立刻停整轮，继续打只会加重风控（不绕过、不重试）
RISK_CODES = {
    35: "IP 地址异常（换网络或等冷却）",
    36: "账号异常（需在浏览器完成验证）",
    37: "登录态失效（请重新登录）",
    401: "未登录",
    403: "被拒绝",
}


class CollectError(RuntimeError):
    """采集前置条件不满足（如 Chrome 未启动），带一个便于展示的 reason。"""

    def __init__(self, reason: str, code: int = 2):
        super().__init__(reason)
        self.reason = reason
        self.code = code


# ---------------------------------------------------------------- 环境


def ensure_writable_temp() -> None:
    """给 Playwright 指定项目内临时目录。

    本机 %TEMP%（C:\\Users\\<user>\\AppData\\Local\\Temp）对 Playwright 的 **Node 驱动**
    不可写，`connect_over_cdp` 会直接 `EPERM: mkdtemp`；而 Python 的 tempfile 反而能成功，
    所以不能靠"试建一个目录"来探测——**无条件**指到项目内 .tmp/pw 最稳。
    """
    import tempfile

    fallback = Path(__file__).resolve().parent.parent / ".tmp" / "pw"
    fallback.mkdir(parents=True, exist_ok=True)
    for k in ("TEMP", "TMP", "TMPDIR"):
        os.environ[k] = str(fallback)
    tempfile.tempdir = str(fallback)


def check_cdp(cdp: str = CDP) -> str:
    """预检 Chrome 调试端口，返回版本串；不可达抛 CollectError。"""
    try:
        import httpx

        # trust_env=False：本机地址绝不能走系统代理（代理会把 127.0.0.1 也拦掉）
        r = httpx.get(f"{cdp}/json/version", timeout=3, trust_env=False)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        return (r.json() or {}).get("Browser", "Chrome")
    except Exception as e:  # noqa: BLE001
        raise CollectError(
            f"Chrome 调试端口不可达（{cdp}）：{type(e).__name__}。"
            f"请先运行 tools/start_boss_chrome.bat 启动 BOSS 专用 Chrome 并登录。"
        ) from e


# ---------------------------------------------------------------- 采集单元


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


def ingest(jobs: list[dict], dsn: str = DSN) -> tuple[dict, int]:
    """把一页岗位写库，返回 (统计, run_id)。"""
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
    conn = store.connect(dsn)
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


# ---------------------------------------------------------------- 计划


def load_plan(conn, source_id: str = "boss") -> dict | None:
    r = conn.execute("SELECT * FROM scrape_plan WHERE source_id=%s", (source_id,)).fetchone()
    return dict(r) if r else None


def build_combos(plan: dict) -> tuple[list[tuple[str, str, str]], int]:
    """(关键词 × 城市) 组合 + 每个组合页数。"""
    keywords = [str(k).strip() for k in (plan.get("keywords") or []) if str(k).strip()]
    cities = list(plan.get("cities") or [])
    # 注意不能用 `or 2`：显式传 0 会被当成"没配"而变成 2，应该夹到下限 1
    raw_pages = plan.get("pages_per_combo")
    pages = max(1, min(int(raw_pages) if raw_pages is not None else 2, MAX_PAGES))
    combos = [(kw, c["code"], c.get("name") or CITY_NAMES.get(c["code"], c["code"]))
              for kw in keywords for c in cities]
    return combos, pages


# ---------------------------------------------------------------- 计划状态回写
#
# 看板「采集控制」卡片和内置调度器都只认 scrape_plan 的这三列：
#   last_run_at    调度器据此判「是否到期」，NULL 视为到期
#   last_status    success / risk / error；risk 会触发 180 分钟冷却
#   last_message   给看板展示的一句话
# 写入逻辑必须只有一份：以前只写在 console/app.py，CLI 路径不回写，
# 导致 CLI 跑成功看板仍显示旧错误、调度器还会立刻重复采集。


def mark_plan_started(conn, source_id: str = "boss") -> None:
    """采集开始时写 `last_run_at`（调用方负责 commit）。

    为什么在「开始」而不是「结束」写：采集一轮要几分钟，
    期间调度器若按旧的 last_run_at 判断，会认为早已到期而重复触发。

    参数:
        conn: 已打开的 psycopg 连接。
        source_id: 计划所属数据源，目前只有 'boss'。
    """
    conn.execute("UPDATE scrape_plan SET last_run_at=now() WHERE source_id=%s",
                 (source_id,))


def plan_status(result: dict) -> str:
    """把 `collect()` 的结果映射成 `scrape_plan.last_status` 的三态值。

    单点定义，避免调用方各写一份判定后跑偏（本缺陷的成因）。
    """
    return ("success" if result.get("ok") else
            "risk" if result.get("risk_code") else "error")


def record_plan_result(conn, result: dict, source_id: str = "boss") -> str:
    """采集结束后把结果写回 `last_status` / `last_message`（调用方负责 commit）。

    状态三态:
        success  正常跑完（result["ok"] 为真）
        risk     触发风控（result["risk_code"] 非空），调度器据此冷却
        error    其他失败（Chrome 未启动、请求异常、计划为空等）

    参数:
        conn: 已打开的 psycopg 连接。
        result: `collect()` 的返回字典，需含 ok / total / message，
                触发风控时还要有 risk_code。
        source_id: 计划所属数据源，目前只有 'boss'。

    返回:
        实际写入的 status，便于调用方复用同一判定打日志。
    """
    status = plan_status(result)
    # 没给 message 时兜底成条数，看板不至于显示空白
    message = (result.get("message") or f"抓取 {result.get('total', 0)} 条")[:300]
    conn.execute(
        "UPDATE scrape_plan SET last_status=%s, last_message=%s WHERE source_id=%s",
        (status, message, source_id),
    )
    return status


# ---------------------------------------------------------------- 主流程


def collect(plan: dict, progress: Callable[[dict], None] | None = None, *,
            no_ingest: bool = False, min_delay: float = 12, max_delay: float = 22,
            cdp: str = CDP, dsn: str = DSN) -> dict:
    """按计划跑一轮采集。

    返回:
        {"ok": bool, "total": 抓到的条数, "upserted": 入库数,
         "pages_done": 已完成页数, "pages_total": 总页数,
         "aborted": bool, "risk_code": int|None, "message": str}

    progress 回调收到的字段（每次翻页一次，含开始/结束）：
        phase: start|page|done|aborted|error
        done/total: 已翻页 / 总页数
        jobs: 累计抓到条数
        upserted: 累计入库条数
        current: "西安 / 开发 第 1 页"
        message: 异常或风控说明
    """
    def emit(**kw) -> None:
        if progress:
            try:
                progress(kw)
            except Exception:  # noqa: BLE001  进度回调不该影响采集
                pass

    ensure_writable_temp()
    combos, pages = build_combos(plan)
    pages_total = len(combos) * pages
    if not combos:
        return {"ok": False, "total": 0, "upserted": 0, "pages_done": 0, "pages_total": 0,
                "aborted": True, "risk_code": None, "error_kind": "plan",
                "message": "采集计划为空（关键词或城市没配）"}

    emit(phase="start", done=0, total=pages_total, jobs=0, upserted=0,
         current="准备连接 Chrome", message=None)
    logger.info("采集计划：%d 词 × %d 城 × %d 页 = %d 页请求",
                len(plan.get("keywords") or []), len(plan.get("cities") or []),
                pages, pages_total)

    try:
        check_cdp(cdp)
    except CollectError as e:
        logger.error("%s", e.reason)
        emit(phase="error", done=0, total=pages_total, jobs=0, upserted=0,
             current="Chrome 未启动", message=e.reason)
        return {"ok": False, "total": 0, "upserted": 0, "pages_done": 0,
                "pages_total": pages_total, "aborted": True, "risk_code": None,
                "error_kind": "cdp", "message": e.reason}

    from playwright.sync_api import sync_playwright

    total = upserted = done = 0
    aborted = False
    risk_code = None
    message = ""

    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(cdp)
        ctx = b.contexts[0] if b.contexts else b.new_context()
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            if "zhipin.com" not in (page.url or ""):
                page.goto("https://www.zhipin.com/", wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2_000)
        except Exception as e:  # noqa: BLE001
            logger.warning("导航首页失败（继续尝试）: %s %s", type(e).__name__, str(e)[:60])

        log_conn = store.connect(dsn)
        for kw, city_code, city_name in combos:
            for pn in range(1, pages + 1):
                current = f"{city_name} / {kw} 第 {pn} 页"
                logger.info("--- %s ---", current)
                emit(phase="page", done=done, total=pages_total, jobs=total,
                     upserted=upserted, current=current, message=None)

                t0 = time.time()
                try:
                    data = fetch_page(page, kw, city_code, pn)
                except Exception as e:  # noqa: BLE001
                    elapsed = int((time.time() - t0) * 1000)
                    logger.error("请求失败: %s %s", type(e).__name__, str(e)[:90])
                    log_step(log_conn, None, kw, city_code, city_name, pn, 0, None,
                             elapsed, "error", f"{type(e).__name__}: {str(e)[:200]}")
                    message = f"请求失败：{type(e).__name__}"
                    aborted = True
                    break

                elapsed = int((time.time() - t0) * 1000)
                code = data.get("code")
                jobs = (data.get("zpData") or {}).get("jobList") or []
                logger.info("code=%s 岗位数=%d 耗时=%dms", code, len(jobs), elapsed)

                run_id = None
                if jobs and not no_ingest:
                    stats, run_id = ingest(jobs, dsn)
                    upserted += sum(stats.values())
                    logger.info("入库: %s", stats)

                log_step(log_conn, run_id, kw, city_code, city_name, pn, len(jobs), code,
                         elapsed, "ok" if jobs else "empty",
                         None if code in (0, None) else f"接口 code={code}")

                done += 1
                total += len(jobs)

                if code in RISK_CODES:
                    risk_code = code
                    message = f"触发风控（code={code}：{RISK_CODES[code]}）"
                    logger.error("%s，立即停止本次采集。不重试、不绕过。", message)
                    aborted = True
                    break

                emit(phase="page", done=done, total=pages_total, jobs=total,
                     upserted=upserted, current=current, message=None)

                if not jobs:
                    logger.info("无更多数据，结束该组合")
                    break
                if pn < pages:
                    delay = random.uniform(min_delay, max_delay)
                    logger.info("随机延迟 %.1fs", delay)
                    time.sleep(delay)
            if aborted:
                break
        log_conn.close()

    logger.info("采集完成，共 %d 条", total)
    emit(phase="aborted" if aborted else "done", done=done, total=pages_total,
         jobs=total, upserted=upserted, current="已停止" if aborted else "已完成",
         message=message or None)
    return {"ok": not aborted, "total": total, "upserted": upserted,
            "pages_done": done, "pages_total": pages_total,
            "aborted": aborted, "risk_code": risk_code,
            "error_kind": ("risk" if risk_code else ("request" if aborted else None)),
            "message": message}
