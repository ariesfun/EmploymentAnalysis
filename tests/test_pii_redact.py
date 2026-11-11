"""原始层 PII 脱敏的回归测试（纯函数，不依赖数据库）。"""
import json
from pathlib import Path

import pytest

from jobmvp.pii import REDACTED, find_pii, redact


def test_json_field_redacted():
    """普通 JSON 形态：联系人/电话字段的值被替换，键名保留。"""
    src = '{"aae004":"张三","aae005":"13900002222","title":"Java开发"}'
    out = redact(src)
    assert "张三" not in out
    assert "13900002222" not in out
    assert '"aae004":"' + REDACTED + '"' in out
    # 岗位字段必须原样保留，否则原始层失去回查价值
    assert '"title":"Java开发"' in out
    # 结果仍是合法 JSON
    assert json.loads(out)["title"] == "Java开发"


def test_html_escaped_field_redacted():
    """HTML 转义 JSON 形态（mohrss 实际写法）：引号样式不能被改坏。"""
    src = '&#034;aae004&#034;:&#034;党女娃&#034;,&#034;aae005&#034;:&#034;13900002222&#034;'
    out = redact(src)
    assert "党女娃" not in out
    assert "13900002222" not in out
    assert out.count("&#034;") == 8          # 四对引号原样保留


def test_boss_fields_redacted():
    """BOSS 的 HR 姓名/职务字段即使没有电话特征也要被清掉。"""
    src = '{"bossName":"王五","bossTitle":"HRBP","jobName":"前端"}'
    out = redact(src)
    assert "王五" not in out
    assert "HRBP" not in out
    assert '"jobName":"前端"' in out


def test_pattern_fallback():
    """不认识的字段名：靠手机号/固话/邮箱模式兜底。"""
    src = "致电 13900002222 或 029-88880000，邮箱 hr@example.com"
    out = redact(src)
    assert "13900002222" not in out
    assert "029-88880000" not in out
    assert "hr@example.com" not in out
    assert out.count(REDACTED) == 3


def test_clean_text_untouched():
    """没有 PII 的文本必须逐字节不变，避免误伤岗位内容。"""
    src = '{"salary":"20-40K·15薪","city":"西安","desc":"负责后端服务，要求 3-5 年经验"}'
    assert redact(src) == src


def test_empty_input():
    """空输入不抛异常。"""
    assert redact("") == ""
    assert redact(None) == ""


def test_find_pii_detects_residue():
    """find_pii 能报出残留；脱敏后的文本必须干净。"""
    dirty = "手机 13900002222"
    assert find_pii(dirty) == ["13900002222"]
    assert find_pii(redact(dirty)) == []


@pytest.mark.parametrize("name", ["aae004", "aae005", "bossName", "bossPhone", "hr_name"])
def test_all_sensitive_keys_covered(name):
    """敏感键名名单逐个验证，防止以后有人从名单里删键。"""
    src = json.dumps({name: "13800138000"}, ensure_ascii=False)
    assert "13800138000" not in redact(src)


def test_real_raw_file_clean_after_redact():
    """拿真实原始层文件跑一遍：脱敏后不得还能检出手机号。

    原始层被 .gitignore 挡住、可能不存在（CI/新克隆），此时跳过而不是失败。
    """
    root = Path(__file__).resolve().parent.parent / "data" / "raw" / "mohrss"
    files = sorted(root.rglob("*.json"))[:3] if root.exists() else []
    if not files:
        pytest.skip("本地无原始层样本")
    for path in files:
        body = json.loads(path.read_text(encoding="utf-8"))["body"]
        assert find_pii(redact(body)) == [], path.name
