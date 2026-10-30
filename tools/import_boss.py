"""导入 BOSS 直聘数据（第三方工具导出的 JSON）到本项目。

只做「入库」这一段：读 JSON → 字段映射 → PII 过滤 → 复用现有
normalize（薪资/地区/岗类/技能）→ upsert（source_job_id 去重）。
去重、薪资 K 显示、指标、看板全部自动生效。

为什么这么拆
------------
取数（登录态、CDP 旁听、风控）交给成熟的第三方工具（boss-zhipin-scraper /
boss-agent-cli / boss-cli），本项目只负责它最擅长的「标准化 + 去重 + 指标 + 看板」。
两者松耦合：第三方升级不影响本项目，本项目也不需要碰 Chrome。

支持格式
--------
- 数组：[{...}, {...}]
- {jobList: [...]} / {jobs: [...]} / {data: [...]} / {items: [...]}
- {zpData: {jobList: [...]}}（BOSS 接口原始结构）

用法
----
    python tools/import_boss.py path/to/jobs.json
    python tools/import_boss.py jobs.json --dry-run     # 只解析预览，不写库

合规
----
个人学习研究用途。不采 HR 个人信息（bossName/bossTitle/bossAvatar 等）：
映射层根本不取这些字段，且 source_config 白名单 + sanitize 再兜一层。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # 支持 python tools/xxx.py 直接运行

from jobmvp import store
from jobmvp.adapter import sanitize
from jobmvp.runner import load_dicts, normalize_item


def _pick(d: dict, *keys: str):
    """按顺序取第一个非空字段（兼容不同工具的字段命名）。"""
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def to_item(raw: dict) -> dict | None:
    """把第三方 JSON 的一条记录映射成项目 item；缺 jobId/标题则返回 None。"""
    jid = _pick(raw, "encryptJobId", "jobId", "id", "job_id", "source_job_id")
    title = _pick(raw, "jobName", "title", "job_title", "name")
    if not jid or not title:
        return None

    city = _pick(raw, "cityName", "city", "city_name")
    district = _pick(raw, "areaDistrict", "district", "area_district")
    loc = _pick(raw, "location", "area")
    if not loc:
        loc = "·".join(str(x) for x in (city, district) if x)

    url = _pick(raw, "url", "jobUrl", "link")
    if not url:
        url = f"https://www.zhipin.com/job_detail/{jid}.html"

    return {
        "source_job_id": str(jid),
        "url": url,
        "title_raw": str(title),
        "location_raw": loc or None,
        "salary_raw": _pick(raw, "salaryDesc", "salary", "salary_desc"),
        "experience_raw": _pick(raw, "jobExperience", "experience", "exp"),
        "edu": _pick(raw, "jobDegree", "degree", "edu"),
        "company_name": _pick(raw, "brandName", "companyName", "company", "brand_name"),
        "posted_at": _pick(raw, "postedAt", "posted_at", "publishTime"),
    }


def load_rows(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for k in ("jobList", "jobs", "data", "list", "items"):
            v = data.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        zp = data.get("zpData")
        if isinstance(zp, dict) and isinstance(zp.get("jobList"), list):
            return [x for x in zp["jobList"] if isinstance(x, dict)]
        return [data]
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description="导入 BOSS JSON 到本项目")
    ap.add_argument("json_path", help="第三方工具导出的 JSON 文件")
    ap.add_argument("--source-id", default="boss")
    ap.add_argument("--dry-run", action="store_true", help="只解析预览，不写库")
    args = ap.parse_args()

    rows = load_rows(args.json_path)
    print(f"读到 {len(rows)} 条原始记录")
    if not rows:
        print("没有可导入的记录")
        return 2

    dsn = os.environ.get("JOBMVP_DSN", "postgresql://mvp:mvp@127.0.0.1:5432/jobmvp")
    conn = store.connect(dsn)
    cfg = conn.execute(
        "SELECT field_whitelist FROM source_config WHERE source_id=%s", (args.source_id,)
    ).fetchone()
    if not cfg:
        print(f"source_config 缺少 {args.source_id}，请先运行 tools/seed_dicts.py")
        return 2
    whitelist = cfg["field_whitelist"]
    matcher, rules, regions = load_dicts(conn)

    items = [it for it in (to_item(r) for r in rows) if it]
    print(f"可映射 {len(items)} 条（跳过 {len(rows) - len(items)} 条缺 jobId/标题）")
    if not items:
        return 2

    if args.dry_run:
        print("\n预览前 5 条（source_job_id | 标题 | 薪资 | 地区 | 公司）:")
        for it in items[:5]:
            print(f"  {it['source_job_id']} | {it['title_raw']} | {it['salary_raw']} | "
                  f"{it['location_raw']} | {it['company_name']}")
        print("\n--dry-run：未写库。")
        return 0

    run_id = store.start_run(conn, args.source_id, "import")
    stats = {"new": 0, "changed": 0, "reopened": 0, "seen": 0}
    for it in items:
        item = sanitize(it, whitelist)                 # 白名单 + PII 兜底
        rec = normalize_item(conn, item, matcher, rules, regions, raw_path="import")
        ev = store.upsert_job(conn, run_id, args.source_id, rec)
        stats[ev] = stats.get(ev, 0) + 1
    conn.commit()
    store.finish_run(conn, run_id, "success", None,
                     fetched=len(rows), parsed=len(items),
                     upserted=sum(stats.values()),
                     parse_failed=len(rows) - len(items), closed=0)
    conn.commit()
    print("导入完成:", stats)
    print("提示：看板/指标基于视图实时刷新，无需额外操作。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
