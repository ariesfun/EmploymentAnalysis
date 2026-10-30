"""来源适配器注册表：source_id -> 工厂函数。

新增来源两步：
1. 在 `jobmvp/sources/` 下实现 `SourceAdapter`（通常继承 `HttpAdapter`）；
2. 在此注册，并在 `source_config` 插入一行（**默认 enabled=false**）。
"""
from __future__ import annotations

from typing import Callable

import httpx

from .adapter import SourceAdapter
from .sources.mohrss import MohrssAdapter

REGISTRY: dict[str, Callable[[], SourceAdapter]] = {
    "mohrss": lambda: MohrssAdapter(
        httpx.Client(timeout=25, follow_redirects=True),
        "http://job.mohrss.gov.cn",
    ),
}
