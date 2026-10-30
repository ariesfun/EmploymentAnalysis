"""来源适配器注册表：source_id -> 工厂函数。

新增来源两步：
1. 在 `jobmvp/sources/` 下实现 `SourceAdapter`（通常继承 `HttpAdapter`）；
2. 在此注册，并在 `source_config` 插入一行（**默认 enabled=false**）。
"""
from __future__ import annotations

import os
from typing import Callable

import httpx

from .adapter import SourceAdapter
from .sources.boss import BossAdapter
from .sources.mohrss import MohrssAdapter

REGISTRY: dict[str, Callable[[], SourceAdapter]] = {
    # A 级：政府公共就业平台
    "mohrss": lambda: MohrssAdapter(
        httpx.Client(timeout=25, follow_redirects=True),
        "http://job.mohrss.gov.cn",
    ),
    # B 级：商业招聘平台，默认关闭，启用需审批备注。
    # 环境变量：BOSS_MODE=http|browser、BOSS_KEYWORD、BOSS_CITY
    "boss": lambda: BossAdapter(
        httpx.Client(timeout=30, follow_redirects=True),
        "https://www.zhipin.com",
        keyword=os.environ.get("BOSS_KEYWORD", "Java"),
        city_code=os.environ.get("BOSS_CITY", "101010100"),
        mode=os.environ.get("BOSS_MODE", "http"),
    ),
}
