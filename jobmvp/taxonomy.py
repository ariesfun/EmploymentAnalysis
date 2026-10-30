"""初始词表（代码侧的「出厂字典」）。

运行时以数据库里的 dict_category / dict_skill / dict_region 为准，
本文件只用于首次播种（tools/seed_dicts.py）与单元测试。

约定：
- 岗类规则按**具体 → 泛化**排列，priority 升序、首个命中生效；
- ASCII 技能别名加词边界，避免 Go 命中 Google、Java 命中 JavaScript。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------- 岗类规则
# (岗类, 关键词元组)；顺序即优先级
CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("算法/AI", ("算法", "机器学习", "深度学习", "大模型", "人工智能", "NLP", "自然语言",
                 "计算机视觉", "推荐系统", "强化学习", "模型训练", "LLM", "AI工程")),
    ("数据", ("数据分析", "数据开发", "数据仓库", "数仓", "数据工程", "大数据", "BI工程",
              "ETL", "Hadoop", "Spark", "Flink", "数据治理", "数据产品", "数据挖掘")),
    ("前端开发", ("前端", "Web前端", "H5", "React", "Vue", "小程序开发", "页面开发",
                  "JavaScript", "TypeScript", "Node.js")),
    ("移动开发", ("Android", "iOS", "移动端", "客户端开发", "Flutter", "鸿蒙", "安卓", "APP开发")),
    ("测试", ("测试", "QA工程", "自动化测试", "测试开发", "性能测试", "功能测试")),
    ("运维/SRE", ("运维", "SRE", "DevOps", "系统管理员", "云计算", "容器", "Kubernetes",
                  "K8s", "网络工程", "机房", "IDC", "技术支持")),
    ("网络安全", ("网络安全", "信息安全", "渗透测试", "安全工程师", "等保")),
    ("嵌入式/硬件", ("嵌入式", "单片机", "硬件", "电子工程", "PCB", "FPGA", "驱动开发",
                     "射频", "通信工程", "电气工程")),
    ("后端开发", ("后端", "服务端", "Java", "Golang", "Go开发", "Python开发", "PHP",
                  "C++", "C#", ".NET", "微服务", "架构师", "中间件", "分布式",
                  "开发工程师", "软件开发", "程序员", "全栈")),
    ("产品/项目", ("产品经理", "项目经理", "需求分析", "产品专员", "实施工程", "项目管理")),
    ("设计", ("UI设计", "UX", "交互设计", "视觉设计", "平面设计", "美工", "设计师")),
    ("机械/制造", ("机械", "工艺", "设备工程", "数控", "焊接", "质检", "模具", "装配",
                   "维修工程", "生产管理", "车间")),
    ("建筑/工程", ("造价", "施工", "监理", "家装", "装饰", "土建", "给排水", "暖通",
                   "测绘", "工程管理", "预算员")),
    ("物流/仓储", ("仓管", "仓储", "叉车", "配送", "快递", "物流", "货运", "司机", "理货")),
    ("教育/培训", ("老师", "教师", "教务", "课程顾问", "培训", "讲师", "助教",
                   "规划师", "教练")),
    ("普工/操作", ("普工", "操作工", "机修", "铆焊", "电工", "焊工", "技工", "学徒",
                   "CNC", "流水线", "包装工")),
    ("销售/市场", ("销售", "市场", "渠道", "客户经理", "商务", "客服", "运营",
                   "业务员", "顾问", "店长", "拓展")),
    ("服务/餐饮", ("服务员", "厨师", "餐饮", "保洁", "保安", "家政", "美容", "前台")),
    ("职能", ("人力", "人事", "行政", "财务", "会计", "法务", "采购", "文员", "助理",
              "主管", "储备干部", "专员")),
)

_ASCII_RE = re.compile(r"^[\x00-\x7f]+$")


def keyword_to_pattern(keyword: str) -> str:
    """把关键词转成正则：ASCII 短词加边界，中文直接转义。"""
    kw = keyword.strip()
    if _ASCII_RE.match(kw) and len(kw) <= 4:
        return r"(?<![A-Za-z0-9+#])" + re.escape(kw) + r"(?![A-Za-z+#])"
    return re.escape(kw)


def category_rows() -> list[tuple[str, str, int]]:
    """产出 (pattern, category, priority)，供播种使用。"""
    rows: list[tuple[str, str, int]] = []
    for idx, (category, keywords) in enumerate(CATEGORY_RULES):
        alt = "|".join(keyword_to_pattern(k) for k in keywords)
        rows.append((alt, category, (idx + 1) * 10))
    return rows


# ---------------------------------------------------------------- 技能别名
# canonical -> 别名元组（全部会被写入 dict_skill，含 canonical 自身）
SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "Python": ("Python",), "Java": ("Java", "JVM", "JDK"),
    "C++": ("C++", "CPP"), "C#": ("C#", "CSharp", ".NET"),
    "Go": ("Go", "Golang", "Go语言"), "Rust": ("Rust",),
    "JavaScript": ("JavaScript", "JS开发", "ES6"), "TypeScript": ("TypeScript",),
    "PHP": ("PHP",), "SQL": ("SQL",), "MySQL": ("MySQL",),
    "PostgreSQL": ("PostgreSQL", "Postgres"), "Redis": ("Redis",),
    "MongoDB": ("MongoDB", "Mongo"), "ClickHouse": ("ClickHouse",),
    "Hadoop": ("Hadoop", "HDFS"), "Spark": ("Spark",), "Flink": ("Flink",),
    "Kafka": ("Kafka",), "Hive": ("Hive",), "Linux": ("Linux", "Unix", "CentOS", "Ubuntu"),
    "Docker": ("Docker", "容器化"), "Kubernetes": ("Kubernetes", "K8s"),
    "Spring": ("Spring", "SpringBoot", "Spring Cloud"),
    "Django": ("Django",), "Flask": ("Flask",), "FastAPI": ("FastAPI",),
    "React": ("React",), "Vue": ("Vue",), "Node.js": ("Node.js", "NodeJS"),
    "Android": ("Android", "安卓"), "iOS": ("iOS", "Swift", "Objective-C"),
    "Flutter": ("Flutter",), "Qt": ("Qt",),
    "TensorFlow": ("TensorFlow",), "PyTorch": ("PyTorch", "Torch"),
    "机器学习": ("机器学习", "Machine Learning"),
    "深度学习": ("深度学习", "Deep Learning"),
    "大模型": ("大模型", "LLM", "Transformer", "GPT"),
    "NLP": ("NLP", "自然语言处理"),
    "计算机视觉": ("计算机视觉", "OpenCV", "图像识别"),
    "数据分析": ("数据分析", "数据建模", "指标体系"),
    "数据仓库": ("数据仓库", "数仓", "维度建模"),
    "ETL": ("ETL", "数据管道"), "Tableau": ("Tableau",),
    "Power BI": ("Power BI", "PowerBI"), "Excel": ("Excel", "VBA"),
    "Shell": ("Shell", "Bash脚本"), "Git": ("Git",),
    "CI/CD": ("CI/CD", "Jenkins", "持续集成"),
    "Prometheus": ("Prometheus", "Grafana"), "Nginx": ("Nginx",),
    "微服务": ("微服务", "服务治理", "Dubbo"),
    "分布式": ("分布式", "高并发", "负载均衡"),
    "嵌入式": ("嵌入式", "单片机", "STM32"), "FPGA": ("FPGA", "Verilog", "VHDL"),
    "PCB": ("PCB", "电路设计", "硬件设计"),
    "通信协议": ("TCP/IP", "MQTT", "Modbus", "串口通信"),
    "网络安全": ("网络安全", "渗透测试", "等保", "漏洞"),
    "产品设计": ("产品设计", "需求分析", "原型", "Axure"),
    "项目管理": ("项目管理", "PMP", "敏捷开发", "Scrum"),
    "英语": ("英语", "English", "CET-6", "六级"),
}


def skill_rows() -> list[tuple[str, str]]:
    """产出 (alias, canonical)。"""
    rows: list[tuple[str, str]] = []
    for canonical, aliases in SKILL_ALIASES.items():
        for alias in aliases:
            rows.append((alias, canonical))
    return rows
