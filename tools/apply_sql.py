"""按序执行 sql/ 下的建表与视图脚本（幂等，可重复运行）。

用法
----
    python tools/apply_sql.py                    # 默认业务库 jobmvp
    python tools/apply_sql.py --dsn postgresql://mvp:mvp@127.0.0.1:5432/jobmvp_test
    python tools/apply_sql.py --dry-run          # 只列出将执行的脚本

说明
----
- 文件按文件名排序执行（001 → 006），每个文件在一个事务里跑完，失败即回滚。
- 所有脚本都用 CREATE ... IF NOT EXISTS / CREATE OR REPLACE，重复执行安全。
- 005/006 含初始数据（采集计划 / 求职意向单行），用 ON CONFLICT DO NOTHING 保证幂等。
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import psycopg

ROOT = pathlib.Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
DEFAULT_DSN = "postgresql://mvp:mvp@127.0.0.1:5432/jobmvp"


def main() -> int:
    ap = argparse.ArgumentParser(description="执行 sql/ 下全部脚本")
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = sorted(SQL_DIR.glob("*.sql"))
    if not files:
        print(f"未找到 SQL 文件：{SQL_DIR}")
        return 1

    print(f"待执行 {len(files)} 个脚本：")
    for f in files:
        print(f"  - {f.name}")
    if args.dry_run:
        return 0

    with psycopg.connect(args.dsn, autocommit=False) as conn:
        for f in files:
            sql = f.read_text(encoding="utf-8")
            try:
                with conn.transaction():
                    conn.execute(sql)
                print(f"✓ {f.name}")
            except Exception as e:  # noqa: BLE001
                print(f"✗ {f.name}: {type(e).__name__}: {str(e)[:160]}")
                return 2

    with psycopg.connect(args.dsn) as conn:
        n_job = conn.execute("SELECT count(*) FROM job").fetchone()[0]
        n_plan = conn.execute("SELECT count(*) FROM scrape_plan").fetchone()[0]
        n_pref = conn.execute("SELECT count(*) FROM job_preference").fetchone()[0]
    print(f"\n完成。job={n_job} 条，scrape_plan={n_plan} 行，job_preference={n_pref} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
