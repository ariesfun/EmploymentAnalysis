-- 007_scrape_step_log.sql  采集步骤明细日志
--
-- 背景：run_log 只记「一次运行」的汇总（fetched/parsed/upserted），
-- 采集过程中每一步（关键词 × 城市 × 页码）的返回码、条数、耗时、异常都看不到，
-- 出问题时无法定位是「哪一步、为什么」失败。
-- 本表把每个采集步骤落库，供看板「采集日志」页排查。

CREATE TABLE IF NOT EXISTS scrape_step_log (
  id          bigserial PRIMARY KEY,
  run_id      bigint REFERENCES run_log(run_id) ON DELETE CASCADE,
  source_id   text NOT NULL,
  keyword     text,
  city_code   text,
  city_name   text,
  page        int,
  job_count   int     NOT NULL DEFAULT 0,
  code        int,                          -- 接口返回码（BOSS: 0=正常 / 36=风控 / 37=登录失效）
  elapsed_ms  int,                          -- 该步耗时
  status      text    NOT NULL,             -- ok / empty / error
  error       text,                          -- 异常类型与消息（status=error 时）
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scrape_step_run   ON scrape_step_log(run_id);
CREATE INDEX IF NOT EXISTS idx_scrape_step_time  ON scrape_step_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scrape_step_error ON scrape_step_log(status) WHERE status = 'error';
