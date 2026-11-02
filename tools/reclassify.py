"""改完岗类词典后，回填历史数据的 category。

为什么要单独一个脚本：`map_category` 是 Python 正则匹配（比 SQL 正则表达力强，
支持负向断言避免 Java/JavaScript 这类子串误命中），SQL 里复刻不了，
所以词典一改，就得用同一份实现重算历史数据，避免"新数据对、老数据错"。

用法：
    .venv/Scripts/python.exe tools/reclassify.py            # 只补 category IS NULL
    .venv/Scripts/python.exe tools/reclassify.py --all      # 全量重算（改规则优先级后用）

顺带清理 `unmapped_term` 里"现在已经能映射"的词，让待办队列干净。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobmvp import store  # noqa: E402
from jobmvp.normalize import map_category  # noqa: E402
from jobmvp.runner import load_dicts  # noqa: E402

DEFAULT_DSN = os.environ.get("JOBMVP_DSN", "postgresql://mvp:mvp@127.0.0.1:5432/jobmvp")


def main() -> int:
    ap = argparse.ArgumentParser(description="按最新词典回填岗类")
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    ap.add_argument("--all", action="store_true", help="全量重算（默认只补未映射）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = ap.parse_args()

    conn = store.connect(args.dsn)
    _, rules, _ = load_dicts(conn)

    where = "" if args.all else "WHERE category IS NULL"
    rows = conn.execute(f"SELECT job_pk, title_raw, category FROM job {where}").fetchall()
    print(f"待处理 {len(rows)} 条" + ("（全量）" if args.all else "（仅未映射）"))

    changes: dict[str, int] = {}
    updates: list[tuple[str, int]] = []
    still_null = 0
    for r in rows:
        cat = map_category(r["title_raw"], rules)
        if cat is None:
            still_null += 1
            continue
        if cat != r["category"]:
            updates.append((cat, r["job_pk"]))
            changes[cat] = changes.get(cat, 0) + 1

    print(f"可归类 {len(updates)} 条，仍无法归类 {still_null} 条")
    for cat, n in sorted(changes.items(), key=lambda x: -x[1]):
        print(f"  + {cat:<16} {n}")

    if args.dry_run:
        print("dry-run，未写库")
        conn.close()
        return 0

    for cat, pk in updates:
        conn.execute("UPDATE job SET category=%s WHERE job_pk=%s", (cat, pk))
    conn.commit()

    # 清理已能映射的待办词
    terms = conn.execute("SELECT kind, term FROM unmapped_term WHERE kind='category'").fetchall()
    drop = [(t["kind"], t["term"]) for t in terms if map_category(t["term"], rules) is not None]
    for kind, term in drop:
        conn.execute("DELETE FROM unmapped_term WHERE kind=%s AND term=%s", (kind, term))
    conn.commit()

    total = conn.execute("SELECT count(*) AS n FROM job").fetchone()["n"]
    left = conn.execute("SELECT count(*) AS n FROM job WHERE category IS NULL").fetchone()["n"]
    print(f"\n完成：写入 {len(updates)} 条，清理待办词 {len(drop)} 个")
    print(f"未映射剩余 {left}/{total} = {left / total * 100:.1f}%")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
