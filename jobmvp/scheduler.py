"""项目内置采集调度器（不依赖宿主定时任务）。

为什么要有它：采集原本靠 WorkBuddy 的 automation 每小时跑一次 CLI，
换个环境/换个宿主就断了，而且采集进度只有 CLI 的 stdout，看板看不到。
现在调度器跑在**服务进程内**，读 `scrape_plan.interval_minutes` 自己判断到期，
调用 `jobmvp.boss_collect.collect()`，进度通过回调冒泡到看板状态栏。

设计要点：
- 守护线程 + 30 秒 tick，不阻塞 API；
- 启动后延迟 `start_delay` 秒再开始判到期，避免服务刚起来就抢资源；
- 是否到期看 `last_run_at`（采集开始时写），NULL 视为到期；
- 真正"能不能跑"由 trigger 回调决定（内部有 running 占位，重复触发会被拒）；
- 任何异常都只记日志，绝不让调度线程挂掉。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable

from . import store

logger = logging.getLogger("scheduler")


class CollectScheduler(threading.Thread):
    """每 tick_seconds 检查一次 scrape_plan，到期就调用 trigger('auto')。"""

    def __init__(self, dsn: str, trigger: Callable[[str], bool], *,
                 tick_seconds: float = 30.0, start_delay: float = 45.0):
        super().__init__(name="collect-scheduler", daemon=True)
        self.dsn = dsn
        self.trigger = trigger
        self.tick_seconds = tick_seconds
        self.start_delay = start_delay
        self._stop = threading.Event()
        self.last_check: datetime | None = None
        self.last_reason: str = "尚未检查"

    # ---------------------------------------------------------- 生命周期
    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        logger.info("采集调度器启动（tick=%ss，启动延迟=%ss）", self.tick_seconds, self.start_delay)
        if self._stop.wait(self.start_delay):
            return
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception as e:  # noqa: BLE001  调度线程不能死
                logger.warning("调度检查异常: %s %s", type(e).__name__, str(e)[:120])
            if self._stop.wait(self.tick_seconds):
                break
        logger.info("采集调度器已停止")

    # ---------------------------------------------------------- 单次检查
    def check_once(self) -> bool:
        """到期返回 True（并已触发），否则 False。"""
        self.last_check = datetime.now(timezone.utc)
        try:
            conn = store.connect(self.dsn)
        except Exception as e:  # noqa: BLE001
            self.last_reason = f"连库失败：{type(e).__name__}"
            return False
        try:
            row = conn.execute("SELECT * FROM scrape_plan WHERE source_id='boss'").fetchone()
        finally:
            conn.close()

        if not row:
            self.last_reason = "无采集计划"
            return False

        plan = dict(row)
        if not plan.get("enabled"):
            self.last_reason = "自动采集已关闭"
            return False

        interval = int(plan.get("interval_minutes") or 60)
        last = plan.get("last_run_at")
        if last is not None:
            elapsed_min = (datetime.now(timezone.utc) - last).total_seconds() / 60.0
            if elapsed_min < interval:
                self.last_reason = f"未到期（{elapsed_min:.0f}/{interval} 分钟）"
                return False

        ok = self.trigger("auto")
        self.last_reason = "已触发采集" if ok else "已有采集在跑，跳过"
        return ok

    def status(self) -> dict:
        return {
            "alive": self.is_alive(),
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "last_reason": self.last_reason,
            "tick_seconds": self.tick_seconds,
        }
