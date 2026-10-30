# BOSS 岗位定时采集 — 执行记忆

## 关键环境坑（务必遵守）

**不要用 `env -u ...` 前缀跑 .venv 里的 Windows python.exe。**
Git Bash 下 `env -u http_proxy ... python.exe -m ...` 会导致参数丢失：进程 exit 0、
无任何输出、脚本里的写文件也不生效 —— 看起来"成功"，实际代码根本没执行。
（2026-10-30 曾因此误判两次，run_log 无新增记录才发现。）

正确写法：在同一条命令内 `unset` 代理变量再执行：

```bash
unset http_proxy HTTP_PROXY https_proxy HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY
export BOSS_MODE=cdp JOBMVP_DSN="postgresql://mvp:mvp@127.0.0.1:5432/jobmvp"
.venv/Scripts/python.exe -m jobmvp.cli run boss --trigger schedule
```

校验方式：输出必须是 `{'run_id': N, 'status': 'success', ...}` 这样的 dict；
只有 exit code 为 0 而没有输出，视为**未执行**，需排查。

## 历史运行

- 2026-10-30 15:27 — run_id=6，status=success，fetched=1 / parsed=15 / upserted=15 / parse_failed=0 / closed=0。Chrome 9223 正常（Chrome 156）。
- 同日前置记录：run_id=5 (manual, 15:19, parsed 15)；run_id=4 (import, 3)；run_id=3 failed（robots.txt 拦截）；mohrss run 1/2 各 507 条。当时 job 总数 399。

## 备注

- 端口检查：`curl -s -m 5 http://127.0.0.1:9223/json/version`，不可达则跳过，绝不自行拉起 Chrome。
- 遇 CaptchaDetected / status=failed：记录原因即停，不重试、不绕过。
