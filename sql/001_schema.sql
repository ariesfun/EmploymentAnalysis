-- 001_schema.sql  (PostgreSQL；已在 PostgreSQL 16 上执行验证)
CREATE TABLE IF NOT EXISTS source_config (
    source_id        text PRIMARY KEY,
    name             text NOT NULL,
    tier             text NOT NULL CHECK (tier IN ('A','A+','B')),
    enabled          boolean NOT NULL DEFAULT false,      -- 默认关闭
    min_interval_s   numeric NOT NULL DEFAULT 5 CHECK (min_interval_s >= 1),
    max_pages        int     NOT NULL DEFAULT 50,
    close_after_miss int     NOT NULL DEFAULT 3,          -- 连续 N 次完整运行未见才判下架
    min_coverage     numeric NOT NULL DEFAULT 0.7,        -- 本次抓取量/上次成功量 低于此值不做下架判定
    field_whitelist  text[]  NOT NULL,
    approval_note    text,                                -- B 级启用必须填写
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (tier <> 'B' OR NOT enabled OR coalesce(approval_note,'') <> '')
);

CREATE TABLE IF NOT EXISTS run_log (
    run_id      bigserial PRIMARY KEY,
    source_id   text NOT NULL REFERENCES source_config(source_id),
    trigger     text NOT NULL DEFAULT 'schedule',         -- schedule / manual
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status      text NOT NULL DEFAULT 'running'
                CHECK (status IN ('running','success','partial','failed','halted_captcha','halted_manual')),
    fetched     int NOT NULL DEFAULT 0,
    parsed      int NOT NULL DEFAULT 0,
    upserted    int NOT NULL DEFAULT 0,
    parse_failed int NOT NULL DEFAULT 0,
    closed      int NOT NULL DEFAULT 0,
    error       text
);
CREATE INDEX IF NOT EXISTS run_log_source_started ON run_log(source_id, started_at DESC);

CREATE TABLE IF NOT EXISTS parse_error (
    id      bigserial PRIMARY KEY,
    run_id  bigint NOT NULL REFERENCES run_log(run_id),
    url     text,
    reason  text,
    snippet text,
    at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job (
    job_pk         bigserial PRIMARY KEY,
    source_id      text NOT NULL REFERENCES source_config(source_id),
    source_job_id  text NOT NULL,
    url            text,
    title_raw      text NOT NULL,
    category       text,                 -- 标准岗类（未映射为 NULL）
    city           text,
    district       text,
    region_code    text,                 -- 行政区划代码（映射表命中才有）
    salary_raw     text,
    salary_unit    text CHECK (salary_unit IN ('month','day','hour')),
    salary_min     numeric,              -- month: 千元/月；day/hour: 元
    salary_max     numeric,
    salary_months  smallint,             -- 12~16
    salary_ok      boolean NOT NULL DEFAULT false,
    exp_min_years  smallint,
    exp_max_years  smallint,
    edu            text,
    company_name   text,
    skills         text[] NOT NULL DEFAULT '{}',
    posted_at      timestamptz,
    first_seen     timestamptz NOT NULL DEFAULT now(),
    last_seen      timestamptz NOT NULL DEFAULT now(),
    last_seen_run  bigint,
    miss_count     smallint NOT NULL DEFAULT 0,
    status         text NOT NULL DEFAULT 'active' CHECK (status IN ('active','closed')),
    closed_at      timestamptz,
    content_hash   text NOT NULL,
    raw_path       text,
    UNIQUE (source_id, source_job_id)
);
CREATE INDEX IF NOT EXISTS job_status_cat_city ON job(status, category, city);
CREATE INDEX IF NOT EXISTS job_first_seen ON job(first_seen);
CREATE INDEX IF NOT EXISTS job_skills_gin ON job USING gin(skills);

CREATE TABLE IF NOT EXISTS job_event (
    id        bigserial PRIMARY KEY,
    job_pk    bigint NOT NULL REFERENCES job(job_pk),
    run_id    bigint,
    event     text NOT NULL CHECK (event IN ('new','changed','closed','reopened')),
    at        timestamptz NOT NULL DEFAULT now(),
    detail    jsonb
);
CREATE INDEX IF NOT EXISTS job_event_job ON job_event(job_pk, at);

CREATE TABLE IF NOT EXISTS dict_category (          -- 岗类映射：按 priority 升序，首个命中生效
    id serial PRIMARY KEY, pattern text NOT NULL, category text NOT NULL, priority int NOT NULL DEFAULT 100
);
CREATE TABLE IF NOT EXISTS dict_skill (
    alias text PRIMARY KEY, canonical text NOT NULL
);
CREATE TABLE IF NOT EXISTS dict_region (
    city text NOT NULL, district text NOT NULL DEFAULT '', region_code text NOT NULL,
    PRIMARY KEY (city, district)
);
CREATE TABLE IF NOT EXISTS unmapped_term (          -- 未映射项队列，供人工归类
    kind text NOT NULL, term text NOT NULL, cnt int NOT NULL DEFAULT 1, last_seen timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, term)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT now(),
    actor text NOT NULL, action text NOT NULL, target text, detail jsonb
);

-- 同一来源同一时刻只允许一个 running 运行，防止并发运行导致 miss 计数错乱
CREATE UNIQUE INDEX IF NOT EXISTS one_running_per_source ON run_log(source_id) WHERE status = 'running';
