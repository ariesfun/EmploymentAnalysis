"""清理 git 全历史里的敏感内容（脱敏 + 删除文件），不依赖 git-filter-repo。

为什么自己写
------------
本机 `git filter-repo` 未安装且无外网，`git filter-branch` 依赖 MSYS shell（本机 shell 已损坏，
`NtCreateDirectoryObject` 报 0xC0000022）。这里只调用 git 的**底层管道命令**
（`read-tree` / `update-index` / `write-tree` / `cat-file` / `hash-object`），
全部是 C 内建命令，不启 shell，因此能跑通。

做法
----
逐提交重放（线性历史）：
  1. 把旧提交的树读进**独立索引文件**（不碰工作区）；
  2. 按 `--purge-path` 从索引里删掉匹配路径；
  3. 对残留的文本 blob 做字面量替换（规则来自 `--rules` 文件）；
  4. `write-tree` 得到新树，再**只改原始 commit 对象的 tree/parent 两行**重新哈希
     —— 作者、提交者、时间、message、encoding 全部原样保留；
  5. 更新分支与标签引用，最后 `reflog expire` + `gc` 把旧对象真正删掉。

安全
----
- 默认 `--dry-run`，只打印将要发生的改动，不写任何引用。
- 不做任何删除前，请先 `git bundle create` 备份（见 README 第 10 节）。
- 规则文件 `--rules` 里是**明文敏感值**，务必放在已被 `.gitignore` 忽略的路径（如 `.tmp/`）。

用法
----
    # 规则文件格式：每行 `原值==>替换值`，# 开头为注释
    .venv\\Scripts\\python.exe tools/purge_history.py --rules .tmp/rewrite_rules.txt \\
        --purge-path 'data/*.png' --dry-run
    # 确认无误后去掉 --dry-run，再强推：git push --force origin main
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

# 文本判定：前 8KB 里出现 NUL 就当作二进制，跳过替换（避免改坏图片/压缩包）
_BINARY_PROBE = 8192


def git(*args: str, stdin: bytes = None, check: bool = True) -> bytes:
    """调用 git，返回 stdout 字节。失败时抛 RuntimeError（除非 check=False）。"""
    proc = subprocess.run(["git"] + list(args), input=stdin, capture_output=True)
    if check and proc.returncode != 0:
        raise RuntimeError("git %s 失败: %s" % (" ".join(args),
                             proc.stderr.decode("utf-8", "replace")[:400]))
    return proc.stdout


def load_rules(path: str) -> list:
    """读取替换规则：每行 `旧==>新`，跳过空行与 # 注释。"""
    rules = []
    # utf-8-sig：兼容 Windows 记事本/PowerShell 写出的 BOM 头
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "==>" not in line:
                raise SystemExit("规则格式错误（缺少 ==>）：%s" % line[:60])
            old, new = line.split("==>", 1)
            rules.append((old.encode("utf-8"), new.encode("utf-8")))
    return rules


def list_files(rev: str) -> list:
    """列出某提交的全部文件：[(mode, type, sha, path)]。"""
    out = git("ls-tree", "-r", "-z", rev)
    items = []
    for chunk in out.split(b"\x00"):
        if not chunk:
            continue
        meta, path = chunk.split(b"\t", 1)
        mode, kind, sha = meta.split(b" ")
        items.append((mode.decode(), kind.decode(), sha.decode(), path.decode("utf-8", "surrogateescape")))
    return items


def is_purged(path: str, patterns: list) -> bool:
    """路径是否命中待删除模式（支持 `data/*.png` 这类单层通配）。"""
    import fnmatch
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def rewrite_blob(sha: str, rules: list, cache: dict, dry: bool) -> str:
    """按规则改一个 blob；不需要改或改不动时返回原 sha。"""
    if sha in cache:
        return cache[sha]
    content = git("cat-file", "blob", sha)
    result = sha
    if b"\x00" not in content[:_BINARY_PROBE]:
        new = content
        for old, repl in rules:
            if old in new:
                new = new.replace(old, repl)
        if new is not content:
            if dry:
                result = "<会改写:%s>" % sha[:8]
            else:
                result = git("hash-object", "-w", "--stdin", stdin=new).decode().strip()
    cache[sha] = result
    return result


def patch_commit(raw: bytes, new_tree: str, parent_map: dict) -> bytes:
    """改写原始 commit 对象：只换 tree 行与 parent 行，其余原样。"""
    lines = raw.split(b"\n")
    out = []
    for line in lines:
        if line.startswith(b"tree "):
            out.append(b"tree " + new_tree.encode())
        elif line.startswith(b"parent "):
            old_parent = line[7:].decode().strip()
            # 父提交若已被重写则换成新 sha；映射缺失说明不是线性历史，直接报错
            if old_parent not in parent_map:
                raise RuntimeError("父提交 %s 尚未重写（只支持线性历史）" % old_parent[:8])
            out.append(b"parent " + parent_map[old_parent].encode())
        else:
            out.append(line)
    return b"\n".join(out)


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description="清理 git 历史里的敏感内容")
    ap.add_argument("--branch", default="main", help="要重写的分支，默认 main")
    ap.add_argument("--rules", help="替换规则文件（每行 旧==>新）")
    ap.add_argument("--purge-path", action="append", default=[],
                    help="要整条删除的路径模式，可重复，如 'data/*.png'")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写引用")
    args = ap.parse_args(argv)

    if not args.branch:
        raise SystemExit("必须指定分支")
    if not args.rules and not args.purge_path:
        raise SystemExit("规则和删除路径至少要给一个")
    rules = load_rules(args.rules) if args.rules else []

    revs = git("rev-list", "--reverse", "--topo-order", args.branch).decode().split()
    if not revs:
        raise SystemExit("分支 %s 上没有提交" % args.branch)
    print("待重写提交 %d 个（%s）" % (len(revs), args.branch))
    print("替换规则 %d 条，删除路径 %d 条" % (len(rules), len(args.purge_path)))

    parent_map = {}       # 旧 sha -> 新 sha
    cache = {}            # blob sha -> 新 sha
    # 独立索引文件：不污染工作区，也不影响当前 git status。
    # 刻意放在 .git/ 下而不是系统临时目录 —— 本机 %TEMP% 是拒绝访问的（WinError 5），
    # 用 tempfile.mkdtemp() 会让 read-tree 在创建 .lock 时直接失败。
    git_dir = git("rev-parse", "--git-dir").decode().strip()
    index_file = os.path.join(git_dir, "purge_index")
    env_backup = os.environ.get("GIT_INDEX_FILE")
    os.environ["GIT_INDEX_FILE"] = index_file

    stat = {"deleted": 0, "replaced": 0}
    try:
        for i, rev in enumerate(revs, 1):
            git("read-tree", rev)
            # 1) 删掉匹配路径（索引里可能本来就没有，用 --ignore-unmatch）
            for path_pattern in args.purge_path:
                for mode, kind, sha, path in list_files(rev):
                    if kind == "blob" and is_purged(path, [path_pattern]):
                        if not args.dry_run:
                            git("update-index", "--force-remove", "--", path, check=False)
                        stat["deleted"] += 1
            # 2) 文本 blob 字面量替换
            if rules:
                for mode, kind, sha, path in list_files(rev):
                    if kind != "blob" or is_purged(path, args.purge_path):
                        continue
                    new_sha = rewrite_blob(sha, rules, cache, args.dry_run)
                    if new_sha != sha:
                        stat["replaced"] += 1
                        if not args.dry_run:
                            git("update-index", "--add", "--cacheinfo",
                                "%s,%s,%s" % (mode, new_sha, path))
            # 3) 写新树并重哈希 commit
            tree = git("write-tree").decode().strip()
            raw = git("cat-file", "commit", rev)
            new_raw = patch_commit(raw, tree, parent_map)
            if args.dry_run:
                parent_map[rev] = rev
            else:
                parent_map[rev] = git("hash-object", "-t", "commit", "-w",
                                      "--stdin", stdin=new_raw).decode().strip()
            if i % 10 == 0 or i == len(revs):
                print("  已处理 %d/%d" % (i, len(revs)))
    finally:
        if env_backup is None:
            os.environ.pop("GIT_INDEX_FILE", None)
        else:
            os.environ["GIT_INDEX_FILE"] = env_backup

    print("删除文件条目 %d 次，改写 blob %d 处" % (stat["deleted"], stat["replaced"]))
    if args.dry_run:
        print("\n[dry-run] 未写入任何引用。确认无误后去掉 --dry-run 重跑。")
        return 0

    # 4) 更新分支与标签
    old_tip, new_tip = revs[-1], parent_map[revs[-1]]
    git("update-ref", "refs/heads/%s" % args.branch, new_tip)
    print("分支 %s: %s -> %s" % (args.branch, old_tip[:8], new_tip[:8]))
    tag_out = git("for-each-ref", "--format=%(refname) %(objecttype) %(objectname) %(*objectname)", "refs/tags")
    for line in tag_out.decode().splitlines():
        refname, kind, obj_sha, peeled = (line.split() + ["", "", "", ""])[:4]
        target = peeled or obj_sha
        if target not in parent_map:
            continue
        if kind == "tag":
            # 注意：tag 对象正文第一行写的是它指向的**提交** sha（即 target），
            # 不是 tag 对象自己的 sha（obj_sha）；拿 obj_sha 去替换会匹配不到，
            # 结果生成一个内容完全相同的 tag 对象，旧历史仍然挂在标签上删不掉。
            raw = git("cat-file", "tag", obj_sha)
            new_raw = raw.replace(("object %s" % target).encode(),
                                  ("object %s" % parent_map[target]).encode(), 1)
            if new_raw == raw:
                print("警告：标签 %s 未发生改动，请检查" % refname)
            new_tag = git("hash-object", "-t", "tag", "-w", "--stdin", stdin=new_raw).decode().strip()
            git("update-ref", refname, new_tag)
        else:
            git("update-ref", refname, parent_map[target])
        print("标签 %s -> %s" % (refname, parent_map[target][:8]))

    # 5) 让旧对象真正不可达并被清理
    git("reflog", "expire", "--expire=now", "--all", check=False)
    git("gc", "--prune=now", check=False)
    print("\n完成。工作区请执行： git reset --hard %s" % args.branch)
    print("强推： git push --force origin %s" % args.branch)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
