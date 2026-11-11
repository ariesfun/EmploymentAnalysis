"""极简 .env 加载器：把仓库根目录 `.env` 里的键值对注入 `os.environ`。

为什么不用 python-dotenv
------------------------
项目只依赖 psycopg / fastapi / httpx / pytest，为一行需求添一个三方依赖不值当；
`.env` 的语法在本项目里只需要 `KEY=VALUE` 和 `#` 注释两种形态，自己解析足够。

约定
----
- **已存在的环境变量优先**：`.env` 只填补空缺，不会覆盖调用方显式传入的值
  （这样临时用 `$env:JOBMVP_DSN=...` 覆盖配置依然有效）。
- `.env` 本身在 `.gitignore:28` 里，口令不会入库；换机器需要手工复制。
- 找不到 `.env` 时静默返回空字典——CI / 生产环境靠真实环境变量即可。
"""
from __future__ import annotations

import os
from pathlib import Path

# 仓库根目录：本文件在 <root>/jobmvp/env.py，所以上溯两级
ROOT = Path(__file__).resolve().parent.parent


def load_env(path=None) -> dict:
    """读取 .env 并注入 os.environ，返回本次真正写入的键值对。"""
    env_path = Path(path) if path else ROOT / ".env"
    if not env_path.exists():
        return {}

    loaded = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        # 去掉成对的引号，容忍 `KEY="value"` 这种写法
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded
