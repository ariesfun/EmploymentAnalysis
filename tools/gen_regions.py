"""生成行政区划映射表 `jobmvp/data/regions.json`。

数据来自中国公共招聘网前端的地区选择器 `/cjobs/styles/agileui/json/aa12.json`，
共 390 条省/地级市（6 位码，均为 xx0000 或 xxNN00）。

产出结构：{ "6101": "西安市", ... } —— 键是区划码前 4 位，值是地级市全名。
省级码（xx0000）不入表，避免把「云南省」当成城市。

    python -m tools.gen_regions
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

SRC = "http://job.mohrss.gov.cn/cjobs/styles/agileui/json/aa12.json"
OUT = Path(__file__).resolve().parent.parent / "jobmvp" / "data" / "regions.json"


def main() -> int:
    r = httpx.get(SRC, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    pairs = re.findall(r'"label"\s*:\s*"([^"]+)"\s*,\s*"id"\s*:\s*"(\d+)"', r.text)

    mapping: dict[str, str] = {}
    for label, code in pairs:
        if len(code) != 6 or not code.endswith("00"):
            continue
        if code.endswith("0000"):        # 省级，跳过
            continue
        mapping[code[:4]] = label

    # 直辖市的区县码是 xx01xx / xx02xx，其市级码是 xx0000（已被跳过），需单独补
    mapping.update({"1101": "北京市", "1201": "天津市",
                    "3101": "上海市", "5001": "重庆市", "5002": "重庆市"})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=0, sort_keys=True),
        encoding="utf-8",
    )
    # 不要用 ✓ 这类符号：GBK(936) 控制台无法编码，会在写完文件后抛 UnicodeEncodeError。
    print(f"[OK] {OUT.relative_to(OUT.parents[2])}  {len(mapping)} 个地级市")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
