"""字典与源配置播种（幂等）。

    python -m tools.seed_dicts                 # 播种岗类/技能字典 + mohrss 源配置
    python -m tools.seed_dicts --with-regions  # 额外从站点采样城市码，填充 dict_region
    python -m tools.seed_dicts --dsn postgresql://...

设计：DB 里的字典是运行时真值，本脚本只负责「出厂初始化」。
重复执行会覆盖 dict_category / dict_skill（视为受管字典），dict_region 为增量 upsert。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # 支持 python tools/xxx.py 直接运行

from jobmvp.taxonomy import category_rows, skill_rows  # noqa: E402

DEFAULT_DSN = os.environ.get("JOBMVP_DSN", "postgresql://mvp:mvp@localhost/jobmvp")

# 出厂源配置。tier/enabled 是合规属性，这里只给「安全默认值」：
# 一律 enabled=false，B 级必须人工填 approval_note 才能启用。
SOURCES = (
    {
        "source_id": "mohrss",
        "name": "中国公共招聘网",
        "tier": "A",
        "min_interval_s": 2,
        "max_pages": 20,
        "fields": [
            "source_job_id", "url", "title_raw", "location_raw", "salary_raw",
            "experience_raw", "edu", "company_name", "description", "posted_at",
            "region_code",
        ],
    },
    {
        "source_id": "boss",
        "name": "BOSS直聘",
        "tier": "B",
        "min_interval_s": 10,      # B 级频率更保守
        "max_pages": 3,
        "fields": [
            "source_job_id", "url", "title_raw", "location_raw", "salary_raw",
            "experience_raw", "edu", "company_name", "posted_at",
        ],
    },
)


def seed_sources(conn) -> None:
    """写入源配置。已存在的源只更新元数据，**不动 enabled / approval_note**。"""
    for src in SOURCES:
        conn.execute(
            """
            INSERT INTO source_config
                (source_id, name, tier, enabled, min_interval_s, max_pages,
                 close_after_miss, min_coverage, field_whitelist, approval_note)
            VALUES (%s, %s, %s, false, %s, %s, 3, 0.7, %s, NULL)
            ON CONFLICT (source_id) DO UPDATE
                SET name = EXCLUDED.name,
                    tier = EXCLUDED.tier,
                    min_interval_s = EXCLUDED.min_interval_s,
                    field_whitelist = EXCLUDED.field_whitelist
            """,
            (src["source_id"], src["name"], src["tier"],
             src["min_interval_s"], src["max_pages"], src["fields"]),
        )


def seed_categories(conn) -> int:
    rows = category_rows()
    conn.execute("DELETE FROM dict_category")
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO dict_category(pattern, category, priority) VALUES (%s,%s,%s)",
            rows,
        )
    return len(rows)


def seed_skills(conn) -> int:
    rows = skill_rows()
    conn.execute("DELETE FROM dict_skill")
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO dict_skill(alias, canonical) VALUES (%s,%s) "
            "ON CONFLICT (alias) DO UPDATE SET canonical = EXCLUDED.canonical",
            rows,
        )
    return len(rows)


def seed_regions(conn, pages: int = 5, source_id: str = "mohrss") -> int:
    """从站点采样 (城市, 城市码)，填充 dict_region。

    源站的 aab301 就是行政区划代码，采样比内置码表更可靠、也不引入维护成本。
    同一城市可能同时出现市级码与区县码（如 220100 / 220105），
    取**出现次数最多**的那个作为城市级码，避免区县码污染。
    """
    from collections import Counter

    from jobmvp.registry import REGISTRY

    adapter = REGISTRY[source_id]()
    counter: dict[str, Counter] = {}
    for i, url in enumerate(adapter.discover(pages), start=1):
        page = adapter.fetch(url)
        for item in adapter.parse(page):
            city, code = item.get("_city"), item.get("_city_code")
            if city and code:
                counter.setdefault(city, Counter())[code] += 1
        print(f"  · 采样第 {i} 页，累计 {len(counter)} 个城市", file=sys.stderr)

    seen = {city: c.most_common(1)[0][0] for city, c in counter.items()}

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO dict_region(city, district, region_code) VALUES (%s,%s,%s) "
            "ON CONFLICT (city, district) DO UPDATE SET region_code = EXCLUDED.region_code",
            [(c, d, code) for (c, d), code in seen.items()],
        )
    return len(seen)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="seed_dicts")
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    ap.add_argument("--with-regions", action="store_true",
                    help="从站点采样城市码填充 dict_region（需联网）")
    ap.add_argument("--pages", type=int, default=5, help="采样页数")
    args = ap.parse_args(argv)

    with psycopg.connect(args.dsn, autocommit=True) as conn:
        seed_sources(conn)
        n_cat = seed_categories(conn)
        n_skill = seed_skills(conn)
        names = "、".join(f"{x['source_id']}({x['tier']})" for x in SOURCES)
        print(f"✓ source_config: {names}（启用状态未改动）")
        print(f"✓ dict_category: {n_cat} 条规则")
        print(f"✓ dict_skill:    {n_skill} 条别名")
        if args.with_regions:
            n = seed_regions(conn, pages=args.pages)
            print(f"✓ dict_region:   {n} 个城市码")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
