"""标准化：薪资 / 经验 / 技能 / 地区 / 岗类。纯函数，无 IO，便于单测。"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

# ---------- 薪资 ----------
_UNIT = {"k": 1.0, "K": 1.0, "千": 1.0, "万": 10.0}   # 折算为 千元
_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*(千|万|[kK])?\s*[-~～至到]\s*(\d+(?:\.\d+)?)\s*(千|万|[kK])?")
_LOWER = re.compile(r"(\d+(?:\.\d+)?)\s*(千|万|[kK])?\s*元?\s*以[上内]")   # 仅下限，如 3000元以上
_UPPER = re.compile(r"(\d+(?:\.\d+)?)\s*(千|万|[kK])?\s*元?\s*以[下]")       # 仅上限，如 5万以下
_MONTHS = re.compile(r"[·.\s]\s*(\d{2})\s*薪")
_DAY = re.compile(r"元?\s*/\s*(天|日)")
_HOUR = re.compile(r"元?\s*/\s*(时|小时)")
SALARY_MAX_K = 500          # 月薪上限(千元)，超过视为解析异常

@dataclass
class Salary:
    unit: Optional[str] = None      # month / day / hour
    min: Optional[float] = None     # month: 千元/月；day/hour: 元
    max: Optional[float] = None
    months: Optional[int] = None    # 12~16
    ok: bool = False
    reason: Optional[str] = None

def parse_salary(raw: Optional[str]) -> Salary:
    if not raw or not raw.strip():
        return Salary(reason="empty")
    s = raw.strip()
    if "面议" in s:
        return Salary(reason="negotiable")
    m = _RANGE.search(s)
    if not m:
        # 仅下限 / 仅上限：如 "3000元以上/月"、"5万以下" —— 也要结构化出 min/max
        mo, mu = _LOWER.search(s), _UPPER.search(s)
        if mo or mu:
            src = mo or mu
            n, u = float(src[1]), src[2]
            factor = _UNIT.get(u, 0.001 if n >= 1000 else 1.0)
            tail = s[src.end():]
            if _DAY.search(tail):
                unit = "day"
            elif _HOUR.search(tail):
                unit = "hour"
            else:
                unit = "month"
            val = round(n * factor, 3)
            mm = _MONTHS.search(tail)
            months = int(mm[1]) if mm and 12 <= int(mm[1]) <= 16 else None
            if mo:
                return Salary(unit=unit, min=val, max=None, months=months, ok=True, reason="lower_only")
            return Salary(unit=unit, min=None, max=val, months=months, ok=True, reason="upper_only")
        return Salary(reason="no_range")
    lo, lu, hi, hu = float(m[1]), m[2], float(m[3]), m[4]
    unit_tail = s[m.end():]
    if _DAY.search(unit_tail):
        unit, f_lo, f_hi = "day", 1.0, 1.0
    elif _HOUR.search(unit_tail):
        unit, f_lo, f_hi = "hour", 1.0, 1.0
    else:
        unit = "month"
        lu = lu or hu                      # "1.5-2万" 左侧缺省单位继承右侧
        hu = hu or lu
        if lu is None:                     # 纯数字，如 "8000-12000元/月"
            f_lo = f_hi = 0.001 if hi >= 1000 else 1.0
        else:
            f_lo, f_hi = _UNIT[lu], _UNIT[hu]
    lo, hi = lo * f_lo, hi * f_hi
    if lo > hi:
        lo, hi = hi, lo
    mm = _MONTHS.search(unit_tail)
    months = int(mm[1]) if mm and 12 <= int(mm[1]) <= 16 else None
    if unit == "month" and hi > SALARY_MAX_K:
        return Salary(reason="out_of_range")
    return Salary(unit=unit, min=round(lo, 3), max=round(hi, 3), months=months, ok=True)

# ---------- 经验 ----------
_EXP_RANGE = re.compile(r"(\d+)\s*[-~至]\s*(\d+)\s*年")
_EXP_OVER = re.compile(r"(\d+)\s*年以上")
_EXP_UNDER = re.compile(r"(\d+)\s*年以[内下]")

def parse_experience(raw: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """返回 (min_years, max_years)；不限/应届 -> (0, 0)；无法解析 -> (None, None)。"""
    if not raw:
        return None, None
    if any(k in raw for k in ("不限", "应届", "在校")):
        return 0, 0
    if m := _EXP_RANGE.search(raw):
        return int(m[1]), int(m[2])
    if m := _EXP_OVER.search(raw):
        return int(m[1]), None
    if m := _EXP_UNDER.search(raw):
        return 0, int(m[1])
    return None, None

# ---------- 地区 ----------
def split_location(raw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """'北京·海淀区·中关村' / '北京-海淀区' / '北京 海淀区' -> (城市, 区县)"""
    if not raw:
        return None, None
    parts = [p.strip() for p in re.split(r"[·\-\s/]+", raw) if p.strip()]
    return (parts[0] if parts else None, parts[1] if len(parts) > 1 else None)

# ---------- 技能（词典匹配）----------
class SkillMatcher:
    """ASCII 词做边界匹配，避免 'Java' 命中 'JavaScript'、'Go' 命中 'Google'；中文词做子串匹配。"""
    def __init__(self, alias_to_canonical: dict[str, str]):
        self._ascii: list[tuple[re.Pattern, str]] = []
        self._cjk: list[tuple[str, str]] = []
        # 长别名优先，确保 'Spring Boot' 先于 'Spring'
        for alias, canon in sorted(alias_to_canonical.items(), key=lambda kv: -len(kv[0])):
            if alias.isascii():
                pat = re.compile(r"(?<![A-Za-z0-9+#])" + re.escape(alias) + r"(?![A-Za-z+#])", re.I)
                self._ascii.append((pat, canon))
            else:
                self._cjk.append((alias, canon))

    def extract(self, text: str) -> list[str]:
        found: dict[str, None] = {}
        for pat, canon in self._ascii:
            if pat.search(text):
                found[canon] = None
        for alias, canon in self._cjk:
            if alias in text:
                found[canon] = None
        return list(found)

# ---------- 岗类映射 ----------
def map_category(title: str, rules: list[tuple[str, str]]) -> Optional[str]:
    """rules: [(正则, 岗类)]，调用方按 priority 升序传入，首个命中生效；未命中返回 None 并由调用方入未映射队列。"""
    for pattern, category in rules:
        if re.search(pattern, title, re.I):
            return category
    return None
