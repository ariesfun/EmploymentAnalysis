"""命令行入口（供 cron/systemd timer 调用）：python -m jobmvp.cli run <source_id> | reap"""
from __future__ import annotations
import argparse, os, sys
from . import store
from .registry import REGISTRY
from .runner import SourceDisabled, run_source

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="jobmvp")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("source_id"); r.add_argument("--trigger", default="schedule")
    sub.add_parser("reap")
    a = ap.parse_args(argv)
    conn = store.connect(os.environ["JOBMVP_DSN"])
    try:
        if a.cmd == "reap":
            n = store.reap_stale_runs(conn); conn.commit(); print(f"reaped={n}"); return 0
        if a.source_id not in REGISTRY:
            print(f"no adapter registered: {a.source_id}", file=sys.stderr); return 2
        try:
            res = run_source(conn, REGISTRY[a.source_id](), a.source_id, trigger=a.trigger)
        except SourceDisabled:
            print("source disabled; no request made", file=sys.stderr); return 3
        print(res)
        return 0 if res["status"] == "success" else 1          # 非 success 返回非零，便于 cron/监控告警
    finally:
        conn.close()

if __name__ == "__main__":
    sys.exit(main())
