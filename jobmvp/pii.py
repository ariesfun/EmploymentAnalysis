"""原始层 PII 脱敏：写入 data/raw 之前，把联系方式类字段换成占位符。

职责
----
`runner.save_raw()` 落盘的是「整页原文」，其中会夹带招聘方联系人信息：
  - 中国公共招聘网（mohrss）：`aae004` 联系人、`aae005` 联系电话；
  - BOSS 直聘：`bossName` / `bossTitle` / `bossPhone`。
解析层虽然有字段白名单（`adapter.sanitize`），但**原始层是落盘副本，白名单管不到**，
所以必须在写盘前单独脱敏一次。这是「PII 不落原始层」这条口径的唯一执行点。

被谁使用
--------
- `jobmvp/runner.py::save_raw()`（全项目唯一的原始层写盘点）；
- `tests/test_pii_redact.py`（断言脱敏覆盖面）。

关键约束
--------
1. **只脱敏落盘副本，不改内存对象**：`adapter.parse(page)` 读的是内存里的
   `page.body`，因此解析结果与脱敏前完全一致，可重放性也不受影响。
2. **只替换值，不替换键与引号形态**：原文里存在三种引号写法（普通 JSON、
   HTML 转义 JSON `&#034;`、JS 单引号），替换时必须保留原样式，
   否则会把 HTML 里的 JSON 字符串改坏，导致原文无法回查。
3. **宁多勿少**：脱敏是单向的，漏一个就是真漏；多脱一个只损失回查时的联系电话，
   不影响任何岗位字段（标题/公司/薪资/地区都不动）。
4. 纯标准库，不引入依赖；Python 3.8 可运行。
"""
from __future__ import annotations

import re

# 统一占位符：便于在日志/回查时一眼看出「这里原本是联系方式」
REDACTED = "<REDACTED>"

# 需要整字段脱敏的键名（一律小写比较）。命中后整个值被替换成 REDACTED。
# 说明：aae006（单位地址）不在名单内 —— 那是企业办公地址，属公开招聘信息，
# 且地区归一化可能要用；个人信息只有联系人和电话。
_SENSITIVE_KEYS = (
    # mohrss：联系人 / 联系电话
    "aae004", "aae005",
    # BOSS 直聘：HR 姓名 / 职务 / 电话
    "bossname", "bosstitle", "bossphone",
    # 通用同义键（其他源可能用）
    "hrname", "hr_name", "recruiter", "contact", "contactperson",
    "phone", "mobile", "tel", "telephone", "email", "wechat", "qq",
)

# 三种引号形态都要覆盖：`"k":"v"`、`&#034;k&#034;:&#034;v&#034;`、`'k':'v'`
_QUOTE = r"(?:\"|&#0?34;|&#x22;|')"
_KEYS = "|".join(_SENSITIVE_KEYS)

# 命中「键 + 引号 + 冒号 + 引号 + 值 + 引号」，按分组重建，保留原始引号样式
_FIELD_RE = re.compile(
    r"(?P<q1>" + _QUOTE + r")"
    r"(?P<key>" + _KEYS + r")"
    r"(?P<q2>" + _QUOTE + r")\s*:\s*"
    r"(?P<q3>" + _QUOTE + r")"
    r"[^\"'&]{0,200}"                      # 值里不允许再出现引号/&，避免跨字段吞掉内容
    r"(?P<q4>" + _QUOTE + r")",
    re.IGNORECASE,
)

# 模式级兜底：即使字段名不认识，只要出现手机号/固话/邮箱也一律打码。
# 边界用 (?<!\d) / (?!\d) 防止把长数字串（编号、金额）的片段误判成电话。
_RE_MOBILE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_RE_LANDLINE = re.compile(r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)")
_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# 审计用的模式集合：find_pii() 与外部扫描脚本共用同一份定义，避免两处不一致
_ALL_PATTERNS = (_RE_MOBILE, _RE_LANDLINE, _RE_EMAIL)


def _replace_field(match: "re.Match[str]") -> str:
    """把命中字段的值替换成占位符，键名与三对引号原样保留。"""
    return (match.group("q1") + match.group("key") + match.group("q2")
            + ":" + match.group("q3") + REDACTED + match.group("q4"))


def redact(text: str) -> str:
    """对整页文本做脱敏，返回新字符串（不修改入参）。

    执行顺序：先按键名整字段脱敏（能清掉人名这类无规律的串），
    再按手机号/固话/邮箱模式兜底（能清掉不认识的字段名）。
    顺序不能颠倒：先模式后字段的话，字段值已被替换，键名匹配仍然有效，
    但没有必要多跑一遍；先字段后模式可以让模式只处理残留。

    :param text: 原始页面文本（HTML/JSON 均可）
    :return: 脱敏后的文本；输入为空或 None 时返回空串
    """
    if not text:
        return ""
    out = _FIELD_RE.sub(_replace_field, text)
    for pattern in _ALL_PATTERNS:
        out = pattern.sub(REDACTED, out)
    return out


def find_pii(text: str) -> list:
    """列出文本中仍然存在的疑似 PII 片段（去重后最多 20 条），供测试/审计断言用。

    只做模式级检测（字段名不可枚举），因此**不能**用它证明「完全无 PII」，
    但 > 0 就足以证明「存在泄露」。
    """
    if not text:
        return []
    hits = []
    for pattern in _ALL_PATTERNS:
        hits.extend(m.group(0) for m in pattern.finditer(text))
    seen = []
    for item in hits:
        if item not in seen:
            seen.append(item)
    return seen[:20]
