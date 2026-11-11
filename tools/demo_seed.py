"""往测试库灌入一套「全合成」的演示数据，用于给 README 截图或本地看效果。

为什么需要它：看板要看到效果得先有数据，但**真实抓取的数据不能拿来做截图**——
里面有真实公司名、真实岗位明细。本脚本只写虚构内容：公司名统一带"示例"，
岗位标题带"（示例）"，薪资按合成分布随机，URL 全部指向 example.invalid。

用法：

    python tools/demo_seed.py            # 灌数据（会先清空测试库的业务表）
    python tools/demo_seed.py --dry-run  # 只看会动哪些表，不写库

安全闸：只允许对库名以 `_test` 结尾的数据库执行，防止误清业务库。
"""

import argparse
import hashlib
import os
import random
import sys
from datetime import datetime, timedelta

import psycopg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from jobmvp.env import load_env  # noqa: E402

# 清空范围：与 tests/conftest.py 对齐，另加采集计划相关表
TABLES = (
    "job_event, parse_error, job, run_log, audit_log, unmapped_term,"
    " dict_category, dict_skill, dict_region, source_config, job_preference,"
    " scrape_plan, scrape_step_log"
)

COMPANIES = [
    "星辰示例科技", "云梯示例数据", "硅谷示例信息", "青竹示例软件",
    "远山示例智能", "长河示例网络", "白鹭示例计算", "南岭示例电子",
]
CITIES = [
    ("西安", "雁塔区", "610113"), ("西安", "高新区", "610131"), ("成都", "武侯区", "510107"),
    ("北京", "海淀区", "110108"), ("上海", "浦东新区", "310115"), ("深圳", "南山区", "440305"),
    ("杭州", "滨江区", "330108"), ("武汉", "洪山区", "420111"),
]
CATS = {
    "后端开发": ["C++", "Go", "Java", "PostgreSQL", "Redis", "Linux"],
    "前端开发": ["TypeScript", "Vue", "React", "Webpack"],
    "算法/AI": ["PyTorch", "Python", "CUDA", "Transformer"],
    "测试": ["Selenium", "Pytest", "接口测试"],
    "运维/SRE": ["Kubernetes", "Docker", "Prometheus", "Shell"],
    "嵌入式/硬件": ["C", "STM32", "FreeRTOS", "Verilog"],
    "数据": ["SQL", "Spark", "Airflow", "Pandas"],
    "网络安全": ["渗透测试", "BurpSuite", "等保"],
    "移动开发": ["Kotlin", "Swift", "Flutter"],
}
TITLES = {
    "后端开发": ["后端开发工程师", "服务端开发工程师", "C++ 开发工程师", "Go 后端工程师"],
    "前端开发": ["前端开发工程师", "Web 前端工程师", "前端架构师"],
    "算法/AI": ["算法工程师", "机器学习工程师", "CV 算法工程师"],
    "测试": ["测试开发工程师", "自动化测试工程师", "软件测试工程师"],
    "运维/SRE": ["运维开发工程师", "SRE 工程师", "云平台运维工程师"],
    "嵌入式/硬件": ["嵌入式软件工程师", "硬件工程师", "驱动开发工程师"],
    "数据": ["数据开发工程师", "数据分析师", "数仓工程师"],
    "网络安全": ["安全工程师", "渗透测试工程师", "安全运营工程师"],
    "移动开发": ["Android 开发工程师", "iOS 开发工程师", "Flutter 开发工程师"],
}
EDUS = ["大专", "本科", "本科", "本科", "硕士"]


def resolve_dsn() -> str:
    """取测试库 DSN：优先环境变量，其次 .env 里的 TEST_DSN。"""
    dsn = os.environ.get("TEST_DSN") or load_env().get("TEST_DSN")
    if not dsn:
        raise SystemExit("未配置 TEST_DSN（环境变量或 .env）")
    name = dsn.rsplit("/", 1)[-1].split("?")[0]
    if not name.endswith("_test"):
        raise SystemExit("安全检查未通过：目标库 `{0}` 不以 _test 结尾，拒绝写入".format(name))
    return dsn


def seed(dsn: str, dry_run: bool = False) -> None:
    """清空业务表并写入合成数据：2 个来源、6 次运行、200 条岗位。"""
    random.seed(20261111)          # 固定种子，保证每次截图一致
    now = datetime.now().astimezone()

    if dry_run:
        print("[dry-run] 将清空这些表：{0}".format(TABLES))
        print("[dry-run] 将写入 2 个来源 / 6 次运行 / 200 条岗位 / 4 条未映射 / 3 条审计")
        return

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE {0} RESTART IDENTITY CASCADE".format(TABLES))

        cur.execute(
            "INSERT INTO source_config (source_id, name, tier, enabled, min_interval_s, max_pages,"
            " field_whitelist, approval_note) VALUES"
            " ('mohrss_demo', '人社部招聘（示例）', 'A', true, 30, 50, %s, NULL),"
            " ('boss_demo', 'BOSS直聘（示例）', 'B', true, 60, 20, %s, '仅演示，不采集真实站点')",
            (["title", "company", "city", "salary", "skills"], ["title", "company", "city", "salary", "skills"]),
        )

        # 6 次运行记录：最近一次停在 running，其余为 success
        for i in range(5, -1, -1):
            started = now - timedelta(days=i, minutes=7 if i else 3)
            status = "success" if i else "running"
            cur.execute(
                "INSERT INTO run_log (source_id, trigger, started_at, finished_at, status, fetched,"
                " parsed, upserted, parse_failed, closed) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                ("mohrss_demo", "schedule" if i % 2 else "manual", started,
                 None if status == "running" else started + timedelta(seconds=95),
                 status, 180 + i * 7, 172 + i * 6, 40 + i, 1, 2),
            )

        rows = []
        for i in range(200):
            cat = random.choice(list(CATS))
            city, district, code = random.choice(CITIES)
            low = random.choice([6, 8, 10, 12, 15, 18, 20, 25])
            high = low + random.choice([4, 5, 6, 8, 10])
            skills = random.sample(CATS[cat], k=min(3, len(CATS[cat])))
            seen = now - timedelta(days=random.randint(0, 28), hours=random.randint(0, 20))
            sid = "demo-{0:03d}".format(i)
            rows.append((
                "mohrss_demo", sid, "https://example.invalid/job/{0}".format(sid),
                random.choice(TITLES[cat]) + "（示例）",
                cat, city, district, code,
                "{0}-{1}K".format(low, high), "month", low, high, 12, True,
                random.choice([1, 2, 3, 5]), random.choice([3, 5, 8]),
                random.choice(EDUS), random.choice(COMPANIES), skills,
                seen, seen, seen, 0,
                "active" if i % 11 else "closed",
                hashlib.sha256(sid.encode()).hexdigest(),
            ))
        cur.executemany(
            "INSERT INTO job (source_id, source_job_id, url, title_raw, category, city, district,"
            " region_code, salary_raw, salary_unit, salary_min, salary_max, salary_months, salary_ok,"
            " exp_min_years, exp_max_years, edu, company_name, skills, posted_at, first_seen,"
            " last_seen, miss_count, status, content_hash) VALUES"
            " (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            rows,
        )

        cur.execute(
            "INSERT INTO unmapped_term (kind, term, cnt) VALUES"
            " ('skill', 'Rust', 7), ('skill', 'Nginx', 5), ('category', '产品经理', 12), ('city', '苏州', 3)"
        )
        cur.execute(
            "INSERT INTO audit_log (actor, action, target, detail) VALUES"
            " ('console-user', 'enable_source', 'boss_demo', '{\"tier\": \"B\"}'),"
            " ('console-user', 'run_source', 'mohrss_demo', '{\"trigger\": \"manual\"}'),"
            " ('scheduler', 'auto_run', 'mohrss_demo', '{\"interval_s\": 30}')"
        )
        cur.execute(
            "INSERT INTO job_preference (cities, salary_min, salary_max, exp_min, exp_max, skills, categories)"
            " VALUES (ARRAY['西安','成都'], 15, 25, 2, 6, ARRAY['C++','Go','PostgreSQL'],"
            " ARRAY['后端开发','运维/SRE'])"
        )
        cur.execute("SELECT count(*) FROM job")
        print("演示数据写入完成，job 行数 = {0}".format(cur.fetchone()[0]))


def main() -> int:
    """解析参数并执行。"""
    parser = argparse.ArgumentParser(description="往测试库灌入合成演示数据")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写库")
    args = parser.parse_args()
    seed(resolve_dsn(), args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
