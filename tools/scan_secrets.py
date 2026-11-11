"""仓库凭据/个人信息扫描：工作区 + git 全历史。

目的
----
公开仓库前，最危险的不是当前代码，而是**历史里的某一个 blob**：
口令、令牌、手机号、真实姓名一旦进过 git，删文件也删不掉，必须改写历史。

用法
----
    .venv\\Scripts\\python.exe tools/scan_secrets.py            # 工作区 + 全历史
    .venv\\Scripts\\python.exe tools/scan_secrets.py --worktree  # 只扫当前文件
    .venv\\Scripts\\python.exe tools/scan_secrets.py --history   # 只扫历史 blob

退出码：0 = 未发现；1 = 有命中（可挂到 pre-commit / CI）。

注意
----
- 只做正则匹配，不判断上下文，因此**会有误报**；命中项需人工确认。
- 输出里对命中值做了打码（保留前 4 位），避免扫描结果本身又成为泄露源。
"""
from __future__ import annotations

import re
import subprocess
import sys

# 每条规则：(名称, 正则, 说明)。宁可误报，也不要漏报。
RULES = [
    ("PG 连接串中的口令", re.compile(r"postgres(?:ql)?://[^:/\s]+:(?!<)[^@\s]{3,}@"), "明文口令的 DSN"),
    ("超级用户弱口令", re.compile(r"\bpostgres\s*:\s*['\"]?\d{4,}"), "postgres 弱口令"),
    ("OpenAI 风格令牌", re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "API key"),
    ("GitHub 令牌", re.compile(r"\b(?:ghp|gho|ghu|ghs)_[A-Za-z0-9]{20,}"), "GitHub token"),
    ("AWS AccessKey", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS key id"),
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "Google key"),
    ("私钥块", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "私钥"),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "手机号"),
    ("固话", re.compile(r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)"), "固话"),
    ("邮箱", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "邮箱"),
]

# 已知无害、不报的片段：本地演示账号 + 文档占位符 + 测试夹具里的假号码
ALLOW_SUBSTRINGS = (
    "mvp:mvp@",                  # 代码里写死的本地演示库账号，非真实凭据
    "user:pass@",                # 文档里的 DSN 占位符
    "postgres:{pw}@",            # README 里的 format 模板
    "ariesfun2019@outlook.com",  # 作者公开联系邮箱，SECURITY.md 有意公开
    "noreply@",
    "example.com",
    "example.invalid",
    "set-your-contact-url",
    "13800001111",               # 测试夹具的假号码（连号，非真实）
    "13900002222",
    "13700003333",
    "13800138000",               # 夹具：13800138000 是中国移动客服样板号
    "029-88880000",              # 夹具：西安区号 + 假固话
)

# DSN 里的口令若是占位符（{pw} / <pw> / pass / word / xxx / ***）则不算泄露
_RE_PLACEHOLDER_PW = re.compile(r"://[^:/\s]+:(?:\{[^}]*\}|<[^>]*>|pass(?:word)?|REDACTED|xxx+|\*+)@")


def _mask(value: str) -> str:
    """打码：只留前 4 个字符，避免扫描器自己变成泄露源。"""
    return value[:4] + "*" * max(0, len(value) - 4)


def _is_allowed(text: str) -> bool:
    """命中片段是否属于「已知无害」：占位符或夹具。"""
    return any(s in text for s in ALLOW_SUBSTRINGS) or bool(_RE_PLACEHOLDER_PW.search(text))


def scan_text(label: str, text: str) -> list:
    """扫描一段文本，返回命中列表 [(规则名, 说明, 打码值, 位置)]。"""
    hits = []
    for name, regex, desc in RULES:
        for m in regex.finditer(text):
            value = m.group(0)
            # 定位所在行，便于人工复核；占位符判断同时看命中值与整行
            start = text.rfind("\n", 0, m.start()) + 1
            end = text.find("\n", m.end())
            line = text[start:end if end >= 0 else len(text)]
            if _is_allowed(value) or _is_allowed(line):
                continue
            hits.append((name, desc, _mask(value), label))
    return hits


def _git(*args: str) -> str:
    """调用 git 并返回 stdout（解码为 utf-8，失败字符用替换符）。"""
    proc = subprocess.run(["git"] + list(args), capture_output=True)
    return proc.stdout.decode("utf-8", "replace")


def scan_worktree() -> list:
    """扫描工作区里被 git 跟踪的文本文件。"""
    hits = []
    for path in _git("ls-files", "-z").split("\0"):
        if not path:
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            continue
        hits.extend(scan_text(path, text))
    return hits


def scan_history(limit: int = 5000) -> list:
    """扫描全部提交里的所有 blob（按 sha 去重，同一个版本只报一次）。

    用 `git cat-file --batch` 一次喂入 sha，比逐个调用快一个数量级。
    """
    listing = _git("rev-list", "--objects", "--all")
    pairs = []            # [(sha, path)]
    for line in listing.splitlines():
        if not line.strip():
            continue
        parts = line.split(" ", 1)
        pairs.append((parts[0], parts[1] if len(parts) > 1 else ""))
    if not pairs:
        return []

    uniq = {}
    for sha, path in pairs:
        uniq.setdefault(sha, path)
    shas = list(uniq.keys())[:limit]

    hits = []
    proc = subprocess.run(["git", "cat-file", "--batch"],
                          input=("\n".join(shas) + "\n").encode(),
                          capture_output=True)
    data = proc.stdout
    pos = 0
    while pos < len(data):
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        header = data[pos:nl].decode("utf-8", "replace").split()
        pos = nl + 1
        if len(header) < 3:          # "<sha> missing"
            continue
        sha, kind, size = header[0], header[1], int(header[2])
        body = data[pos:pos + size]
        pos += size + 1
        if kind != "blob" or b"\x00" in body[:4096]:   # 跳过二进制
            continue
        label = "history:%s:%s" % (sha[:8], uniq.get(sha, "")[:60])
        hits.extend(scan_text(label, body.decode("utf-8", "replace")))
    return hits


def report(hits: list) -> int:
    """打印结果，返回退出码。"""
    if not hits:
        print("未发现可疑凭据或个人信息。")
        return 0
    # 同一规则 + 同一打码值只报一次，避免 README 的 18 个历史版本刷屏
    seen = set()
    for name, desc, masked, label in hits:
        key = (name, masked)
        if key in seen:
            print("  （同上，另有副本）  %s" % label)
            continue
        seen.add(key)
        print("[%s] %s  → %s   @ %s" % (name, desc, masked, label))
    print("\n命中 %d 处（去重后 %d 组）。请人工确认；确属凭据的先轮换、再清理历史。"
          % (len(hits), len(seen)))
    return 1


def main(argv: list) -> int:
    do_work = "--history" not in argv
    do_hist = "--worktree" not in argv
    hits = []
    if do_work:
        print("== 扫描工作区（git 跟踪的文件）")
        hits.extend(scan_worktree())
    if do_hist:
        print("== 扫描 git 全历史 blob")
        hits.extend(scan_history())
    return report(hits)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
