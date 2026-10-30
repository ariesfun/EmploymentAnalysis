-- 006_job_preference.sql  个人求职意向（单行配置）+ 匹配度打分
--
-- 用于按「期望城市 / 薪资 / 技能 / 岗类」给在招岗位打匹配分，帮助找到契合度高的职位。

CREATE TABLE IF NOT EXISTS job_preference (
  id          int PRIMARY KEY DEFAULT 1,
  cities      text[]  NOT NULL DEFAULT '{}',   -- 期望城市名，如 {西安,成都}
  salary_min  numeric,                          -- 期望月薪下限（K）
  salary_max  numeric,                          -- 期望月薪上限（K）
  skills      text[]  NOT NULL DEFAULT '{}',   -- 期望技能，如 {C++,Linux,MySQL}
  categories  text[]  NOT NULL DEFAULT '{}',   -- 期望岗类，如 {后端开发,嵌入式/硬件}
  exp_min     int,                              -- 期望最低经验年
  exp_max     int,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT single_row CHECK (id = 1)
);

INSERT INTO job_preference(id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- 匹配度视图：城市 25 + 薪资 30 + 技能 35（按交集比例）+ 岗类 10
CREATE OR REPLACE VIEW m_job_match AS
SELECT j.job_pk, j.source_id, j.title_raw, j.company_name, j.city, j.district,
       j.salary_raw, j.salary_min, j.salary_max, j.salary_unit, j.salary_ok,
       j.category, j.skills, j.url, j.posted_at, j.first_seen,
       (
         CASE WHEN j.city = ANY(p.cities) THEN 25 ELSE 0 END
         + CASE WHEN j.salary_min IS NOT NULL AND j.salary_max IS NOT NULL
                     AND p.salary_min IS NOT NULL AND p.salary_max IS NOT NULL
                     AND j.salary_min <= p.salary_max AND j.salary_max >= p.salary_min
                THEN 30 ELSE 0 END
         + CASE WHEN cardinality(p.skills) > 0 AND j.skills && p.skills
                THEN LEAST(35, 35.0 *
                     (SELECT count(*) FROM unnest(j.skills) AS x WHERE x = ANY(p.skills))
                     / cardinality(p.skills))
                ELSE 0 END
         + CASE WHEN j.category = ANY(p.categories) THEN 10 ELSE 0 END
       )::int AS score
FROM m_job_dedup j CROSS JOIN job_preference p
WHERE p.id = 1;
