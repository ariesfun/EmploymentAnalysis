-- 008_scrape_plan_schedule.sql  采集计划补调度字段（项目内置调度器用）
--
-- 背景：采集原来靠宿主（WorkBuddy）的定时任务跑，项目自身不具备调度能力，
-- 换台机器/换个宿主就断了。本迁移给 scrape_plan 补上「间隔」和「上次运行」，
-- 让 jobmvp.scheduler 能在服务进程内自主判断该不该跑。

ALTER TABLE scrape_plan ADD COLUMN IF NOT EXISTS interval_minutes int NOT NULL DEFAULT 60;
ALTER TABLE scrape_plan ADD COLUMN IF NOT EXISTS last_run_at      timestamptz;
ALTER TABLE scrape_plan ADD COLUMN IF NOT EXISTS last_status      text;   -- success / risk / error
ALTER TABLE scrape_plan ADD COLUMN IF NOT EXISTS last_message     text;   -- 上次结果摘要

-- 间隔下限 5 分钟：再短会明显加重风控（一页 30 条 × N 组合）
ALTER TABLE scrape_plan DROP CONSTRAINT IF EXISTS scrape_plan_interval_chk;
ALTER TABLE scrape_plan
  ADD CONSTRAINT scrape_plan_interval_chk CHECK (interval_minutes >= 5 AND interval_minutes <= 1440);

COMMENT ON COLUMN scrape_plan.enabled IS '自动采集开关（看板「采集配置」里的定时采集）';
COMMENT ON COLUMN scrape_plan.interval_minutes IS '自动采集间隔（分钟，5-1440）';
COMMENT ON COLUMN scrape_plan.last_run_at IS '上次采集开始时间（调度器据此判断是否到期）';
