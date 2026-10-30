-- 003_metric_salary_by_category.sql   指标口径 v1.1（**新增视图，不改动 v1 既有口径**）
--
-- 背景：m_salary_pctl 按 (岗类, 城市) 分组，小样本下几乎每个分组都 <30，
--       对「技术岗」这种垂直切口反而拿不到任何分位数。
-- 本视图只按岗类分组，并显式排除未映射岗类（category IS NULL），
-- 作为 v1 的补充；v1 的 m_salary_pctl 保持原样，避免口径漂移。
--
-- 约束：分位数只统计 salary_unit='month' 且 salary_ok 的岗位；样本<30 不输出。

CREATE OR REPLACE VIEW m_salary_pctl_by_category AS
SELECT category,
       count(*)                                                       AS n,
       percentile_cont(0.25) WITHIN GROUP (ORDER BY (salary_min + salary_max) / 2) AS p25_k,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY (salary_min + salary_max) / 2) AS p50_k,
       percentile_cont(0.75) WITHIN GROUP (ORDER BY (salary_min + salary_max) / 2) AS p75_k
FROM job
WHERE status = 'active'
  AND salary_ok
  AND salary_unit = 'month'
  AND category IS NOT NULL
GROUP BY 1
HAVING count(*) >= 30
ORDER BY n DESC;
