"""采集计划状态回写探针（scrape_plan 的 last_run_at / last_status / last_message）。

职责
----
锁住「一轮采集的开始与结束状态必须落到 scrape_plan」这条契约。
全程不联网、不启 Chrome：用 monkeypatch 替换真正的 `collect`。

为什么需要这组探针
------------------
状态回写原先只写在 `console/app.py` 里，CLI 路径 `tools/boss_api_scrape.py`
完全不写。于是 CLI 跑完 30 页成功采集后：看板仍显示上一次的 error 文案；
调度器按 `last_run_at` 判到期，CLI 不更新就等于「从未跑过」，
一启动看板立刻重复采集一轮，有风控风险。

判定
----
每个断言打印 [PASS]/[FAIL]；任一失败即整体失败。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

import pytest

from jobmvp import boss_collect

# scrape_plan.source_id 外键指向 source_config，先把数据源本身播进去
SEED_SOURCE_SQL = """
INSERT INTO source_config(source_id, name, tier, enabled, field_whitelist)
VALUES ('boss', 'BOSS直聘', 'A', true, ARRAY['source_job_id','url','title_raw'])
ON CONFLICT (source_id) DO NOTHING
"""

# 播种一行计划；冲突时把三个状态列清空，保证每个用例从「干净起点」开始
SEED_PLAN_SQL = """
INSERT INTO scrape_plan(source_id, keywords, cities, pages_per_combo,
                        enabled, interval_minutes)
VALUES ('boss', ARRAY['开发'], '[{"code":"101110100","name":"西安"}]'::jsonb, 2, true, 180)
ON CONFLICT (source_id) DO UPDATE
   SET last_run_at = NULL, last_status = NULL, last_message = NULL
"""


def _seed(conn) -> None:
    """播种数据源与 boss 计划，并清空状态列。"""
    conn.execute(SEED_SOURCE_SQL)
    conn.execute(SEED_PLAN_SQL)
    conn.commit()


def _read(conn) -> dict:
    """读回 scrape_plan 的状态三列。"""
    return conn.execute(
        "SELECT last_run_at, last_status, last_message "
        "FROM scrape_plan WHERE source_id='boss'"
    ).fetchone()


def test_mark_started_writes_last_run_at(conn):
    """开始采集要写 last_run_at，否则调度器会认为没跑过。"""
    _seed(conn)
    assert _read(conn)["last_run_at"] is None

    boss_collect.mark_plan_started(conn)
    conn.commit()

    row = _read(conn)
    assert row["last_run_at"] is not None, "[FAIL] last_run_at 仍为空"
    age = (datetime.now(timezone.utc) - row["last_run_at"]).total_seconds()
    assert 0 <= age < 60, f"[FAIL] last_run_at 不是当前时间（差 {age:.0f}s）"


def test_record_success(conn):
    """成功结果写 success，并把条数写进 message。"""
    _seed(conn)
    boss_collect.record_plan_result(
        conn, {"ok": True, "total": 59, "upserted": 59, "message": ""})
    conn.commit()

    row = _read(conn)
    assert row["last_status"] == "success", f"[FAIL] status={row['last_status']}"
    assert "59" in (row["last_message"] or ""), f"[FAIL] message={row['last_message']}"


def test_record_risk_marks_risk(conn):
    """触发风控要写 risk（调度器靠它做 180 分钟冷却）。"""
    _seed(conn)
    boss_collect.record_plan_result(
        conn, {"ok": False, "total": 30, "upserted": 30, "risk_code": 35,
               "message": "触发风控（code=35）"})
    conn.commit()

    row = _read(conn)
    assert row["last_status"] == "risk", f"[FAIL] status={row['last_status']}"
    assert "35" in (row["last_message"] or ""), "[FAIL] 风控码没写进 message"


def test_record_error_keeps_reason(conn):
    """普通失败写 error，并保留失败原因（看板要显示）。"""
    _seed(conn)
    boss_collect.record_plan_result(
        conn, {"ok": False, "total": 0, "upserted": 0,
               "message": "Chrome 调试端口不可达"})
    conn.commit()

    row = _read(conn)
    assert row["last_status"] == "error", f"[FAIL] status={row['last_status']}"
    assert "Chrome" in (row["last_message"] or ""), "[FAIL] 失败原因丢失"


def test_cli_plan_writes_back(monkeypatch, conn):
    """CLI 走 --plan 时，必须把结果回写到 scrape_plan（缺陷复现点）。"""
    _seed(conn)

    # 替换真正的采集：不连 Chrome、不写 job 表，只回一个成功结果
    def fake_collect(plan, progress=None, **kwargs):
        return {"ok": True, "total": 42, "upserted": 42, "pages_done": 2,
                "pages_total": 2, "aborted": False, "risk_code": None,
                "error_kind": None, "message": ""}

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
    from tools import boss_api_scrape as cli

    monkeypatch.setattr(cli.boss_collect, "collect", fake_collect)
    monkeypatch.setattr(sys, "argv", ["boss_api_scrape.py", "--plan"])

    assert cli.main() == 0, "[FAIL] CLI 退出码不是 0"

    row = _read(conn)
    assert row["last_run_at"] is not None, "[FAIL] CLI 没写 last_run_at"
    assert row["last_status"] == "success", f"[FAIL] status={row['last_status']}"
    assert "42" in (row["last_message"] or ""), f"[FAIL] message={row['last_message']}"
