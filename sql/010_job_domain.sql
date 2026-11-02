-- 010_job_domain.sql  把「业务领域」判定收敛成 SQL 函数
--
-- 背景：业务领域原来写在 /api/analytics/domains 的一条大 CASE 里，
-- 岗位明细要显示行业时又得复制一遍。抽成函数后，图表和明细共用同一份口径，
-- 改行业词表只改这里。
--
-- 两段式：
--   fn_company_domain(name)        只按公司名判定，认不出返回 NULL（= 需要推断）
--   fn_job_domain(name, category)  公司名优先，认不出再按岗类反推，最后才「其他行业」

CREATE OR REPLACE FUNCTION fn_company_domain(company_name text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE
    WHEN company_name IS NULL OR company_name = '' THEN NULL
    WHEN company_name ~ '人力资源|劳务' THEN '人力资源服务'
    WHEN company_name ~ '中软|软通|法本|德科|慧博云通|中电金信|柯莱特|佰钧成|中科创达|京北方|文思|博彦|东软|太极|神州数码' THEN 'IT服务/外包'
    WHEN company_name ~ '腾讯|阿里|百度|字节|美团|京东|网易|小米|华为|中兴|快手|滴滴|拼多多|携程' THEN '互联网'
    WHEN company_name ~ '芯|半导体|集成电路|微电子|晶圆|光电' THEN '电子芯片'
    WHEN company_name ~ '医疗|医药|生物|制药|医院|基因' THEN '医疗健康'
    WHEN company_name ~ '教育|培训|学校|学院|职教' THEN '教育培训'
    WHEN company_name ~ '银行|保险|证券|基金|财务|会计|金融|支付' THEN '金融'
    WHEN company_name ~ '轨道|交通|运输|物流|供应链|快递|航空|航运' THEN '交通物流'
    WHEN company_name ~ '汽车|零部件|新能源|锂电' THEN '汽车/新能源'
    WHEN company_name ~ '建筑|建设|工程|地产|置业|装饰' THEN '建筑地产'
    -- 「工业软件」「汽车软件」这类要先判软件，否则会被下面的 工业/汽车 抢走
    WHEN company_name ~ '软件' THEN '信息技术'
    WHEN company_name ~ '制造|机械|设备|工业|材料|化工|钢铁' THEN '制造工业'
    WHEN company_name ~ '传媒|文化|影业|广告|影视' THEN '传媒文化'
    WHEN company_name ~ '贸易|商贸|零售|超市|电商|百货' THEN '商贸零售'
    WHEN company_name ~ '科技|信息|软件|网络|智能|数据|云|技术|通信' THEN '信息技术'
    ELSE NULL END
$$;

CREATE OR REPLACE FUNCTION fn_job_domain(company_name text, category text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT COALESCE(
    fn_company_domain(company_name),
    CASE
      WHEN category IN ('后端开发','前端开发','算法/AI','数据','测试','运维/SRE',
                        '嵌入式/硬件','移动开发','网络安全') THEN '信息技术'
      WHEN category IN ('销售/市场','职能','产品/项目','设计','安全/消防') THEN '企业服务'
      WHEN category IN ('普工/操作','机械/制造','产品研发(非软件)') THEN '制造工业'
      WHEN category = '物流/仓储' THEN '交通物流'
      WHEN category = '建筑/工程' THEN '建筑地产'
      WHEN category = '教育/培训' THEN '教育培训'
      WHEN category = '传媒/内容' THEN '传媒文化'
      ELSE '其他行业'
    END)
$$;

COMMENT ON FUNCTION fn_company_domain(text) IS '仅按公司名判定行业；认不出返回 NULL';
COMMENT ON FUNCTION fn_job_domain(text, text) IS '行业判定：公司名优先，认不出按岗类反推，最后其他行业';
