"""单源运行：合规闸门 → 抓取 → 原始落盘 → 解析 → 标准化 → 入库 → 条件性下架判定。"""
from __future__ import annotations
import hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from . import store
from .adapter import CaptchaDetected, SourceAdapter, Throttle, sanitize
from .normalize import SkillMatcher, map_category, parse_experience, parse_salary, split_location
from .pii import redact

class SourceDisabled(Exception): pass

def load_dicts(conn) -> tuple[SkillMatcher, list[tuple[str, str]], dict[tuple[str, str], str]]:
    skills = {r["alias"]: r["canonical"] for r in conn.execute("SELECT alias,canonical FROM dict_skill")}
    rules = [(r["pattern"], r["category"]) for r in
             conn.execute("SELECT pattern,category FROM dict_category ORDER BY priority,id")]
    regions = {(r["city"], r["district"]): r["region_code"] for r in conn.execute("SELECT * FROM dict_region")}
    return SkillMatcher(skills), rules, regions

def normalize_item(conn, item: dict, matcher, rules, regions, raw_path: str) -> dict:
    city, district = split_location(item.get("location_raw"))
    sal = parse_salary(item.get("salary_raw"))
    emin, emax = parse_experience(item.get("experience_raw"))
    category = map_category(item["title_raw"], rules)
    if category is None:
        store.bump_unmapped(conn, "category", item["title_raw"][:100])
    text = f'{item["title_raw"]} {item.get("description") or ""}'
    rec = dict(item)
    rec.update(
        category=category, city=city, district=district,
        region_code=(item.get("region_code")
                     or regions.get((city or "", district or ""))
                     or regions.get((city or "", ""))),
        salary_unit=sal.unit, salary_min=sal.min, salary_max=sal.max, salary_months=sal.months, salary_ok=sal.ok,
        exp_min_years=emin, exp_max_years=emax, skills=matcher.extract(text), raw_path=raw_path,
    )
    rec.pop("description", None)          # MVP 不落 JD 全文：减少版权/数据权益风险，需要时在原始层回查
    rec["content_hash"] = store.content_hash(item)
    return rec

def save_raw(root: Path, source_id: str, url: str, body: str) -> str:
    """落盘一页原文到原始层，返回文件路径。

    落盘前做 PII 脱敏：整页 HTML 里带招聘方联系人与电话（mohrss 的
    aae004/aae005、BOSS 的 bossName），解析层白名单管不到落盘副本，
    必须在这里拦一次，否则「PII 不落原始层」只是文档承诺。
    注意脱敏只作用于写盘的那份副本：`adapter.parse(page)` 读的是内存里的
    `page.body`，解析结果与脱敏前一致，可重放性不受影响（岗位字段一个不动）。
    """
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d = root / source_id / day
    d.mkdir(parents=True, exist_ok=True)
    p = d / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    p.write_text(json.dumps({"url": url, "body": redact(body)}, ensure_ascii=False))
    return str(p)

def run_source(conn, adapter: SourceAdapter, source_id: str, *, trigger: str = "schedule", actor: str = "scheduler",
               raw_root: Path = Path("data/raw"), sleep: Callable[[float], None] | None = None) -> dict:
    cfg = store.load_source(conn, source_id)
    if cfg is None or not cfg["enabled"]:
        raise SourceDisabled(source_id)                       # 合规闸门：未启用的源绝不发请求
    run_id = store.start_run(conn, source_id, trigger)
    store.audit(conn, actor, "run_start", source_id, {"run_id": run_id, "trigger": trigger})
    conn.commit()
    matcher, rules, regions = load_dicts(conn)
    th = Throttle(float(cfg["min_interval_s"]), **({"sleep": sleep} if sleep else {}))
    c = dict(fetched=0, parsed=0, upserted=0, parse_failed=0, closed=0)
    status, error = "success", None
    try:
        for url in adapter.discover(cfg["max_pages"]):
            th.wait()
            page = adapter.fetch(url)
            c["fetched"] += 1
            raw_path = save_raw(raw_root, source_id, url, page.body)
            for item in adapter.parse(page):
                try:
                    item = sanitize(item, cfg["field_whitelist"])
                    if not item.get("source_job_id") or not item.get("title_raw"):
                        raise ValueError("missing source_job_id/title_raw")
                    rec = normalize_item(conn, item, matcher, rules, regions, raw_path)
                    store.upsert_job(conn, run_id, source_id, rec)
                    c["parsed"] += 1; c["upserted"] += 1
                except Exception as e:                         # 单条失败：记录样本，继续
                    c["parse_failed"] += 1
                    store.log_parse_error(conn, run_id, url, repr(e), json.dumps(item, ensure_ascii=False, default=str))
            conn.commit()
    except CaptchaDetected as e:
        status, error = "halted_captcha", str(e)               # 不重试、不绕过、不做下架判定
        store.audit(conn, "system", "captcha_halt", source_id, {"run_id": run_id, "detail": str(e)})
    except Exception as e:
        status, error = "failed", repr(e)
    if status == "success":
        prev = store.last_success_parsed(conn, source_id)
        if c["parse_failed"] and c["parse_failed"] > 0.2 * max(c["parsed"] + c["parse_failed"], 1):
            status, error = "partial", "parse_failed > 20%"
        elif prev and c["parsed"] < float(cfg["min_coverage"]) * prev:
            status, error = "partial", f"coverage {c['parsed']}/{prev} < {cfg['min_coverage']}"
    if status == "success":                                   # 只有完整且覆盖达标才允许判定下架
        c["closed"] = store.sweep_closed(conn, source_id, run_id, cfg["close_after_miss"])
    store.finish_run(conn, run_id, status, error, **c)
    conn.commit()
    return {"run_id": run_id, "status": status, "error": error, **c}
