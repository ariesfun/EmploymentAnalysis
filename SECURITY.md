# 安全与合规说明

本文件说明**本项目的安全边界、数据口径，以及如何报告问题**。
仓库公开前请连同 `README.md` 顶部的「合规声明」一起阅读。

---

## 1. 报告安全问题

- **不要**在公开 Issue 里贴真实数据、cookie、密钥或可复现的凭据。
- 优先使用 GitHub 的 **Security → Report a vulnerability**（私密通道）。
- 邮件渠道：`ariesfun2019@outlook.com`（仅用于安全问题，勿用于功能咨询）。
- 收到报告后会在 7 天内给出初步答复。

## 2. 本项目的设计边界（这些「不算漏洞」）

| 事项 | 说明 |
|---|---|
| 不接收 / 不存储招聘方联系方式 | `jobmvp/adapter.py:16` 的 `PII_FIELDS` + `jobmvp/adapter.py:42` 的 `sanitize()` 在解析层丢弃；`jobmvp/pii.py` 在原始层落盘前再脱敏一次 |
| 不落 JD 全文 | `jobmvp/runner.py:37` `rec.pop("description", None)`，只保留标题用于技能抽取 |
| 对外只输出聚合指标 | 公司/技能/城市榜各限 15 行；不分发 JD 原文与公司级明细 |
| 控制台默认拒绝所有请求 | `console/app.py:194` 未配置 `JOBMVP_API_KEY` 时一律 401，且用 `hmac.compare_digest` 比对 |
| 采集遵守 robots.txt | `jobmvp/adapter.py:74` 逐 URL 校验；命中验证码直接 `CaptchaDetected` 停止，不绕过 |
| 仓库内无凭据 | 无 `.env`、`pgpass.conf`、cookie、`storage_state`；`data/`、`logs/`、`reference/` 被 `.gitignore` 排除 |

> 若你认为上表中某一条**没有真正做到**（例如某条路径仍会落 PII），那才是需要报告的问题。

## 3. 使用者的责任

- 采集行为由使用者发起，**数据合法性、账号风控、法律责任由使用者承担**。
- 请勿把 `tools/start_boss_chrome.bat` 的调试端口（9223）暴露到公网；该端口等同于**已登录浏览器会话**。
- 请勿用本项目采集未成年人信息、非公开信息，或用于骚扰、批量营销。
- 生产部署必须替换：`JOBMVP_DSN` 口令、`JOBMVP_API_KEY`、`HttpAdapter.user_agent` 中的联系方式。

## 4. 密钥策略

- 仓库**任何历史版本**都不应出现口令/令牌；提交前请自行执行：
  `python tools/scan_secrets.py`
- 若曾误提交：**先轮换密钥**，再清理历史。只清理历史而不轮换，等于没修。

## 5. 支持范围

本项目是个人作品，不提供 SLA；安全修复会以最小改动方式合入。
