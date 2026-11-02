"""BOSS 主动调 API 采集 —— CLI 薄壳。

核心逻辑在 `jobmvp/boss_collect.py`（控制台「立即采集」、内置调度器、本 CLI 共用同一份），
这里只负责参数解析、控制台日志和退出码：

    0  成功
    1  计划未启用 / 无配置
    2  Chrome 调试端口不可达（环境未就绪，定时任务应跳过而非报警）
    4  触发风控被中止（IP/账号异常，需人工处理）
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobmvp import boss_collect, store  # noqa: E402

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def _setup_logging() -> logging.Logger:
    """采集是独立进程：控制台 + logs/scrape.log（FileHandler，多进程不抢滚动）。"""
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s scrape: %(message)s", "%Y-%m-%d %H:%M:%S")
    lg = logging.getLogger("scrape")
    if not lg.handlers:
        fh = logging.FileHandler(LOG_DIR / "scrape.log", encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(message)s"))
        lg.addHandler(fh)
        lg.addHandler(sh)
        lg.setLevel(logging.INFO)
        lg.propagate = False
    return lg


logger = _setup_logging()


def main() -> int:
    ap = argparse.ArgumentParser(description="BOSS 主动调 API 采集")
    ap.add_argument("--plan", action="store_true",
                    help="从 scrape_plan 表读取关键词/城市/页数（看板「采集配置」保存的）")
    ap.add_argument("--keyword", default="开发")
    ap.add_argument("--city", default="101110100", help="BOSS 城市码，西安=101110100")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--page-size", type=int, default=30, help="（兼容保留，固定 30）")
    ap.add_argument("--no-ingest", action="store_true", help="只抓不写库")
    ap.add_argument("--min-delay", type=float, default=12)
    ap.add_argument("--max-delay", type=float, default=22)
    args = ap.parse_args()

    if args.plan:
        conn = store.connect(boss_collect.DSN)
        plan = boss_collect.load_plan(conn)
        conn.close()
        if not plan or not plan.get("enabled"):
            logger.warning("采集计划未启用或无配置，退出")
            return 1
    else:
        plan = {
            "keywords": [args.keyword],
            "cities": [{"code": args.city,
                        "name": boss_collect.CITY_NAMES.get(args.city, args.city)}],
            "pages_per_combo": args.pages,
        }

    def on_progress(p: dict) -> None:
        if p.get("phase") == "page" and p.get("current"):
            pass          # 每页的明细由 collect 内部 logger 输出，这里不重复打

    result = boss_collect.collect(
        plan, progress=on_progress, no_ingest=args.no_ingest,
        min_delay=args.min_delay, max_delay=args.max_delay,
    )

    logger.info("采集结果：抓取 %d 条 / 入库 %d / %d 页%s",
                result["total"], result["upserted"], result["pages_done"],
                f" · {result['message']}" if result["message"] else "")

    kind = result.get("error_kind")
    if kind == "cdp":
        return 2
    if kind == "risk":
        return 4
    if kind == "request":
        return 4
    if kind == "plan":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
