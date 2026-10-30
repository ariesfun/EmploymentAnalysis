-- 005_scrape_plan.sql  采集计划配置（可视化配置关键词 / 城市 / 每组合页数）
--
-- 背景：此前 BOSS 采集的关键词与城市散在环境变量（BOSS_KEYWORD / BOSS_CITY）里，
-- 界面上看不到也改不了。本表把采集计划落库，看板可读写，定时任务按此执行。

CREATE TABLE IF NOT EXISTS scrape_plan (
  source_id        text PRIMARY KEY REFERENCES source_config(source_id) ON DELETE CASCADE,
  keywords         text[] NOT NULL DEFAULT '{}',
  cities           jsonb  NOT NULL DEFAULT '[]',   -- [{"code":"101110100","name":"西安"}]
  pages_per_combo  int    NOT NULL DEFAULT 2,      -- 每个「关键词 × 城市」抓几页（30 条/页）
  enabled          boolean NOT NULL DEFAULT true,
  updated_at       timestamptz NOT NULL DEFAULT now()
);

-- 默认计划：技术方向关键词 × 西安/成都/重庆
-- 用 WHERE EXISTS 保护：测试库会 TRUNCATE source_config，没有 boss 源时跳过而不是报外键错
INSERT INTO scrape_plan(source_id, keywords, cities, pages_per_combo)
SELECT 'boss',
       ARRAY['开发','C++','前端','测试','算法'],
       '[{"code":"101110100","name":"西安"},{"code":"101270100","name":"成都"},{"code":"101040100","name":"重庆"}]'::jsonb,
       2
WHERE EXISTS (SELECT 1 FROM source_config WHERE source_id = 'boss')
ON CONFLICT (source_id) DO NOTHING;
