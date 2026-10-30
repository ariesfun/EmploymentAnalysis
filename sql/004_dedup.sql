-- 004_dedup.sql  业务去重（**必须在 001/002/003 之后执行**）
--
-- 背景：源站对同一岗位会用多个不同的 job_id 重复发布（相同 公司+岗位+城市+区+薪资），
--       仅靠 source_job_id 唯一约束无法消除。看板与活跃岗指标若直接基于 job 表，
--       会把同一岗位反复计入，污染活跃数、薪资分位、技能热度。
--
-- 做法：在 job 之上建 m_job_dedup，按业务键 (title_raw, company_name, city, district, salary_raw)
--       分组，每组保留 posted_at 最新的一条；posted_at 相同则取 first_seen 最新、再 job_pk 最大。
--       看板列表与"活跃岗位"类指标全部引用本视图，物理层不动（下次采集重复进来也自动滤掉）。
--
-- 口径分工：
--   * m_job_dedup / m_active_jobs / m_salary_pctl / m_salary_pctl_by_category / m_skill_weekly
--     均基于去重后的活跃岗位；
--   * m_quality / m_new_jobs_daily / m_job_lifetime 仍基于原始 job
--     （质量诊断、入库量、生命周期本就该看原始数据）。

CREATE OR REPLACE VIEW m_job_dedup AS
SELECT j.*
FROM (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY title_raw, company_name, city, district, salary_raw
    ORDER BY posted_at DESC NULLS LAST,
             first_seen DESC NULLS LAST,
             job_pk     DESC
  ) AS rn
  FROM job
  WHERE status = 'active'
) j
WHERE rn = 1;

-- 活跃岗位数：去重
CREATE OR REPLACE VIEW m_active_jobs AS
SELECT category, city, count(*) AS active_jobs
FROM m_job_dedup GROUP BY 1,2;

-- 薪资分位：去重 + 仅双边界参与（(min+max)/2 需要 min、max 都非空）
CREATE OR REPLACE VIEW m_salary_pctl AS
SELECT category, city, count(*) AS n,
       percentile_cont(0.25) WITHIN GROUP (ORDER BY (salary_min+salary_max)/2) AS p25_k,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY (salary_min+salary_max)/2) AS p50_k,
       percentile_cont(0.75) WITHIN GROUP (ORDER BY (salary_min+salary_max)/2) AS p75_k
FROM m_job_dedup
WHERE salary_ok AND salary_unit = 'month'
  AND salary_min IS NOT NULL AND salary_max IS NOT NULL
GROUP BY 1,2 HAVING count(*) >= 30;

-- 薪资分位（按岗类）：口径 v1.2
--   * 去重 + 双边界 + 排除未映射；
--   * 最小样本从 30 放宽到 10：本产品是「技术岗垂直切口」，去重后单岗类样本稀疏，
--     30 阈值下基本只剩 1 个岗类；放宽到 10 让更多岗类可见，但前端会标注「样本<20 谨慎参考」。
CREATE OR REPLACE VIEW m_salary_pctl_by_category AS
SELECT category, count(*) AS n,
       percentile_cont(0.25) WITHIN GROUP (ORDER BY (salary_min+salary_max)/2) AS p25_k,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY (salary_min+salary_max)/2) AS p50_k,
       percentile_cont(0.75) WITHIN GROUP (ORDER BY (salary_min+salary_max)/2) AS p75_k
FROM m_job_dedup
WHERE salary_ok AND salary_unit = 'month'
  AND salary_min IS NOT NULL AND salary_max IS NOT NULL
  AND category IS NOT NULL
GROUP BY 1 HAVING count(*) >= 10 ORDER BY n DESC;

-- 技能热度：去重，避免重复岗位放大计数
CREATE OR REPLACE VIEW m_skill_weekly AS
SELECT date_trunc('week', first_seen)::date AS week, category, s AS skill, count(*) AS cnt
FROM m_job_dedup, unnest(skills) AS s
GROUP BY 1,2,3;
