-- 002_metrics.sql  指标口径 v1（口径变更必须升版本号并留档）
-- 约束：分位数只统计 salary_unit='month' 且 salary_ok 的岗位；样本<30 不输出

CREATE OR REPLACE VIEW m_new_jobs_daily AS
SELECT date_trunc('day', first_seen)::date AS day, category, city, count(*) AS new_jobs
FROM job GROUP BY 1,2,3;

CREATE OR REPLACE VIEW m_active_jobs AS
SELECT category, city, count(*) AS active_jobs
FROM job WHERE status = 'active' GROUP BY 1,2;

-- 存续天数：仅统计已下架岗位（active 岗位是右删失数据，不并入统计）
CREATE OR REPLACE VIEW m_job_lifetime AS
SELECT category, city, count(*) AS n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (closed_at - first_seen))/86400) AS p50_days
FROM job WHERE status = 'closed'
GROUP BY 1,2 HAVING count(*) >= 30;

CREATE OR REPLACE VIEW m_salary_pctl AS
SELECT category, city, count(*) AS n,
       percentile_cont(0.25) WITHIN GROUP (ORDER BY (salary_min+salary_max)/2) AS p25_k,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY (salary_min+salary_max)/2) AS p50_k,
       percentile_cont(0.75) WITHIN GROUP (ORDER BY (salary_min+salary_max)/2) AS p75_k
FROM job
WHERE status = 'active' AND salary_ok AND salary_unit = 'month'
GROUP BY 1,2 HAVING count(*) >= 30;

CREATE OR REPLACE VIEW m_skill_weekly AS
SELECT date_trunc('week', first_seen)::date AS week, category, s AS skill, count(*) AS cnt
FROM job, unnest(skills) AS s
GROUP BY 1,2,3;

CREATE OR REPLACE VIEW m_quality AS            -- 数据质量面板
SELECT source_id,
       count(*)                                              AS total,
       round(100.0*avg(salary_ok::int),1)                    AS salary_parse_pct,
       round(100.0*avg((region_code IS NOT NULL)::int),1)    AS region_match_pct,
       round(100.0*avg((category IS NOT NULL)::int),1)       AS category_map_pct,
       round(100.0*avg((cardinality(skills)>0)::int),1)      AS skill_hit_pct
FROM job WHERE status='active' GROUP BY 1;
