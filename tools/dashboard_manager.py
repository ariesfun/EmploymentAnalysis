"""看板启停入口（转发器）：真正的实现只在 scripts/dashboard_manager.py，
这里只做转发，避免两套逻辑再次分叉（旧副本曾缺 --no-use-colors，
日志里会重新出现 ANSI 转义）。

用法与实现完全一致：python tools/dashboard_manager.py [start|stop|restart|status]
"""

import os
import runpy

TARGET = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts",
                 "dashboard_manager.py")
)

runpy.run_path(TARGET, run_name="__main__")