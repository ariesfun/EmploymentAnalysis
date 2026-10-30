"""控制台可视化首页（单文件、无外部依赖）。

页面本身不含任何数据，所有数据都通过带 X-API-Key 的接口获取；
`key` 从 URL 查询参数读取（?key=xxx），不落 localStorage 以外的地方。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>招聘市场数据实时分析</title>
<style>
:root{--ink:#1f2328;--muted:#6b7280;--line:#e6e8ec;--bg:#f6f7f9;--card:#fff;
--accent:#2f6feb;--ok:#0f9d58;--warn:#d97706;--bad:#d92d20}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.6;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.app{display:flex;min-height:100vh}
.sidebar{width:216px;background:#fff;border-right:1px solid var(--line);display:flex;flex-direction:column;position:sticky;top:0;height:calc(100vh - 30px);transition:width .18s ease;flex-shrink:0}
.sidebar.collapsed{width:62px}
.brand{display:flex;align-items:center;gap:8px;padding:12px 10px;border-bottom:1px solid var(--line);min-height:56px}
.brand .logo{width:28px;height:28px;flex-shrink:0;display:flex}
.brand .logo svg{width:28px;height:28px;display:block;border-radius:9px;box-shadow:0 2px 6px rgba(79,140,255,.28)}
.brand-text{flex:1;font-size:13px;font-weight:650;line-height:1.3;white-space:nowrap;overflow:hidden}
.sidebar.collapsed .brand{justify-content:center;padding:12px 0}
.sidebar.collapsed .brand-text,.sidebar.collapsed .brand .logo{display:none}
.menu{flex:1;padding:10px 8px;display:flex;flex-direction:column;gap:2px;overflow:hidden}
.menu-item{display:flex;align-items:center;gap:10px;padding:9px 10px;border:none;background:none;border-radius:8px;cursor:pointer;color:var(--muted);font-size:13px;font-family:inherit;text-align:left;white-space:nowrap;transition:background .12s}
.menu-item:hover{background:#f6f7f9;color:var(--ink)}
.menu-item.active{background:#eef3ff;color:var(--accent);font-weight:600}
.menu-item svg{width:18px;height:18px;flex-shrink:0}
.sidebar.collapsed .menu-item .label{display:none}
.collapse-btn{width:28px;height:28px;display:flex;align-items:center;justify-content:center;border:none;background:none;border-radius:6px;cursor:pointer;color:var(--muted);flex-shrink:0}
.collapse-btn:hover{background:#f6f7f9;color:var(--ink)}
.collapse-btn svg{width:18px;height:18px}
.side-foot{padding:12px 14px;border-top:1px solid var(--line);font-size:11px;color:var(--muted);display:flex;align-items:center;gap:6px;white-space:nowrap}
.side-foot .ver{font-weight:650;color:var(--ink);letter-spacing:.2px}
.side-foot .tag{padding:1px 6px;border:1px solid var(--line);border-radius:4px;font-size:10px;background:#f8f9fb}
.sidebar.collapsed .side-foot{justify-content:center;padding:12px 0}
.sidebar.collapsed .side-foot .tag{display:none}
.main{flex:1;min-width:0;padding:24px 24px 48px}
.statusbar{position:fixed;left:0;right:0;bottom:0;height:30px;background:#fff;border-top:1px solid var(--line);
display:flex;align-items:center;gap:18px;padding:0 16px;font-size:11.5px;color:var(--muted);z-index:100;overflow-x:auto}
.statusbar .st{display:flex;align-items:center;gap:6px;white-space:nowrap}
.statusbar .dot{width:7px;height:7px;border-radius:50%;background:#9aa1ab;flex-shrink:0}
.statusbar .dot.ok{background:#22a06b}
.statusbar .dot.bad{background:#e5484d}
.statusbar .dot.warn{background:#f5a623}
header{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;
flex-wrap:wrap;margin-bottom:18px}
h1{font-size:20px;margin:0;font-weight:650;letter-spacing:-.2px}
.sub{color:var(--muted);font-size:12.5px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:16px 18px;margin-bottom:14px}
.card h2{font-size:13.5px;margin:0 0 2px;font-weight:600}
.card .hint{font-size:12px;color:var(--muted);margin:0 0 12px}
.grid{display:grid;gap:14px}
.g2{grid-template-columns:1fr 1fr}
.g4{grid-template-columns:repeat(4,1fr)}
.kpi{background:#fff;border:1px solid var(--line);border-radius:12px;padding:13px 15px}
.kpi .k{font-size:12px;color:var(--muted)}
.kpi .v{font-size:23px;font-weight:650;letter-spacing:-.5px;margin-top:2px}
.kpi .u{font-size:12px;color:var(--muted);font-weight:400;margin-left:2px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{padding:6px 8px;text-align:left;border-bottom:1px solid #f0f1f4}
th{color:var(--muted);font-weight:500;font-size:12px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;
border:1px solid var(--line);background:#f8f9fb;color:var(--muted)}
.pill.ok{background:#e8f6ee;border-color:#bfe3cd;color:#0b7a43}
.pill.bad{background:#fdeceb;border-color:#f5c6c2;color:#b3261e}
.pill.warn{background:#fff5e6;border-color:#f5d6a8;color:#9a5b00}
.bar{height:7px;background:#eef1f5;border-radius:999px;overflow:hidden;margin-top:5px}
.bar>i{display:block;height:100%;background:var(--accent);border-radius:999px}
.empty{color:#9aa1ab;font-size:12.5px;padding:10px 0}
.mod{display:none}
.mod.active{display:block}

.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
.filters select,.filters input{padding:5px 9px;border:1px solid #d5d9e0;border-radius:8px;
font-size:12.5px;background:#fff;color:var(--ink)}
.filters input{min-width:200px}
.filters button,.pager button{padding:5px 12px;border:1px solid #d5d9e0;border-radius:8px;
background:#fff;font-size:12.5px;cursor:pointer}
.filters button:hover,.pager button:hover{background:#f6f7f9}
.pager{display:flex;gap:10px;align-items:center;justify-content:flex-end;
margin-top:10px;font-size:12.5px;color:var(--muted)}
.pager button:disabled{opacity:.45;cursor:not-allowed}
td a{color:var(--accent);text-decoration:none;white-space:nowrap}
td a:hover{text-decoration:underline}
tr:hover td{background:#fafbfc}
.err{background:#fdeceb;border:1px solid #f5c6c2;color:#b3261e;padding:10px 14px;
border-radius:10px;font-size:12.5px;margin-bottom:14px}
code{background:#f2f4f7;padding:1px 5px;border-radius:4px;font-size:12px}
svg{display:block}
footer{margin-top:22px;text-align:center;color:#9aa1ab;font-size:11.5px}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar" id="sidebar">
    <div class="brand">
      <span class="logo">
        <svg viewBox="0 0 32 32" width="28" height="28">
          <defs>
            <linearGradient id="brandGrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stop-color="#4f8cff"/>
              <stop offset="100%" stop-color="#6d5efc"/>
            </linearGradient>
          </defs>
          <rect width="32" height="32" rx="9" fill="url(#brandGrad)"/>
          <rect x="7.4" y="18" width="3.6" height="6.6" rx="1.3" fill="#fff" opacity="0.82"/>
          <rect x="14.2" y="13" width="3.6" height="11.6" rx="1.3" fill="#fff" opacity="0.92"/>
          <rect x="21" y="8" width="3.6" height="16.6" rx="1.3" fill="#fff"/>
          <path d="M9.2 15.2 L15.9 10.8 L22.8 6.2" stroke="#fff" stroke-width="1.6" fill="none" stroke-linecap="round" opacity="0.7"/>
        </svg>
      </span>
      <span class="brand-text">招聘市场数据<br>实时分析</span>
      <button class="collapse-btn" id="collapseBtn" title="折叠/展开菜单">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
      </button>
    </div>
    <nav class="menu" id="menu">
      <button class="menu-item active" data-mod="overview" title="概览">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/></svg>
        <span class="label">概览</span>
      </button>
      <button class="menu-item" data-mod="market" title="市场结构">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21h18"/><rect x="5" y="10" width="3" height="8"/><rect x="10.5" y="5" width="3" height="13"/><rect x="16" y="13" width="3" height="5"/></svg>
        <span class="label">市场结构</span>
      </button>
      <button class="menu-item" data-mod="skills" title="技能需求">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 6l-5 6 5 6M16 6l5 6-5 6"/></svg>
        <span class="label">技能需求</span>
      </button>
      <button class="menu-item" data-mod="salary" title="薪资分析">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v20M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
        <span class="label">薪资分析</span>
      </button>
      <button class="menu-item" data-mod="jobs" title="岗位明细">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>
        <span class="label">岗位明细</span>
      </button>
      <button class="menu-item" data-mod="pref" title="求职意向">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/></svg>
        <span class="label">求职意向</span>
      </button>
      <button class="menu-item" data-mod="config" title="采集配置">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        <span class="label">采集配置</span>
      </button>
    </nav>
    <div class="side-foot">
      <span class="ver">v0.1.0</span><span class="tag">内部</span>
    </div>
  </aside>
  <main class="main">
  <header>
    <div>
      <h1>招聘市场数据实时分析</h1>
      <div class="sub" id="sub">加载中…</div>
    </div>
    <div class="sub" id="meta"></div>
  </header>
  <div id="banner"></div>

  <section class="mod active" data-mod="overview">
    <div class="grid g4" id="kpis"></div>

    <div class="grid g2">
      <div class="card">
        <h2>数据质量</h2>
        <p class="hint">口径见 m_quality 视图</p>
        <div id="quality"></div>
      </div>
      <div class="card">
        <h2>数据源</h2>
        <p class="hint">合规闸门：未启用的源不发请求</p>
        <div id="sources"></div>
      </div>
    </div>

    <div class="card">
      <h2>新发岗位趋势</h2>
      <p class="hint">按 first_seen 归集到日（不是源站发布时间）</p>
      <div id="trend"></div>
    </div>
  </section>

  <section class="mod" data-mod="market">
    <div class="grid g2">
      <div class="card">
        <h2>岗类分布（在招）</h2>
        <p class="hint">未映射岗位显示为「未映射」，进 unmapped_term 队列<span class="asof"></span></p>
        <div id="families"></div>
      </div>
      <div class="card">
        <h2>城市分布（在招）</h2>
        <p class="hint">按标准化后的地级市统计<span class="asof"></span></p>
        <div id="cities"></div>
      </div>
    </div>
    <div class="card">
      <h2>业务领域分布</h2>
      <p class="hint">按公司名关键词粗分类（信息技术 / 财务金融 / 交通物流 / 电子芯片 等）<span class="asof"></span></p>
      <div id="domains" style="display:flex;justify-content:center"></div>
    </div>
  </section>

  <section class="mod" data-mod="skills">
    <div class="grid g2">
      <div class="card">
        <h2>技能热度（Top 15）</h2>
        <p class="hint">从岗位标题/描述提取的技能词频（去重后活跃岗位）<span class="asof"></span></p>
        <div id="skills"></div>
      </div>
      <div class="card">
        <h2>技能 × 岗类矩阵</h2>
        <p class="hint">Top 技能在各岗类的出现次数（颜色越深越密集）<span class="asof"></span></p>
        <div id="skillMatrix"></div>
      </div>
    </div>
  </section>

  <section class="mod" data-mod="salary">
    <div class="card">
      <h2>薪资分位（按岗类，P25 / P50 / P75）</h2>
      <p class="hint">
        把该岗类所有岗位的月薪<b>从低到高排成一队</b>：
        <b>P25</b> 是排在第 1/4 位的（偏低的价）、
        <b>P50</b> 是正中间那个（典型水平，一半岗位比它低、一半比它高）、
        <b>P75</b> 是排在第 3/4 位的（偏高的价）。
        也就是说 <b>P25～P75 之间，就是大多数公司开出的价</b>。
        口径（v1.3）：只统计在招、能解析出月薪区间（min/max 都有）的岗位；已按「岗位+公司+城市」业务去重，每组保留最新发布；样本少于 10 条的岗类不展示，<b>样本&lt;20 的谨慎参考</b>。
      </p>
      <div id="salary"></div>
    </div>
    <div class="grid g2">
      <div class="card">
        <h2>薪资分布直方图</h2>
        <p class="hint">月薪区间（K）的岗位数量分布<span class="asof"></span></p>
        <div id="salaryHist"></div>
      </div>
      <div class="card">
        <h2>经验要求分布</h2>
        <p class="hint">按岗位要求的最低经验分档<span class="asof"></span></p>
        <div id="expDist"></div>
      </div>
    </div>
  </section>

  <section class="mod" data-mod="jobs">
    <div class="card">
      <h2>在招岗位（可直接投递）</h2>
      <p class="hint">点「查看详情」跳到源站岗位页，可在原站投递；这里只有岗位侧字段，不含 HR 联系方式</p>
      <div class="filters">
        <select id="fCat"><option value="">全部岗类</option></select>
        <select id="fCity"><option value="">全部城市</option></select>
        <select id="fSort" onchange="loadJobs(0)">
          <option value="posted">最新发布</option>
          <option value="salary_desc">月薪高→低</option>
          <option value="salary_asc">月薪低→高</option>
        </select>
        <input id="fQ" placeholder="搜岗位名 / 公司名" onkeydown="if(event.key==='Enter')loadJobs(0)">
        <button onclick="loadJobs(0)">查询</button>
        <span class="sub" id="jobCount"></span>
      </div>
      <div id="jobList"></div>
      <div class="pager">
        <button id="prevBtn" onclick="pageJobs(-1)">上一页</button>
        <span id="pageInfo"></span>
        <button id="nextBtn" onclick="pageJobs(1)">下一页</button>
      </div>
    </div>

    <div class="grid g2">
      <div class="card">
        <h2>运行历史</h2>
        <p class="hint">run_log</p>
        <div id="runs"></div>
      </div>
      <div class="card">
        <h2>未映射岗位名（待归类）</h2>
        <p class="hint">按出现次数排序，供人工补 dict_category</p>
        <div id="unmapped"></div>
      </div>
    </div>

    <div class="card">
      <h2>审计日志</h2>
      <p class="hint">源启停、运行开始、验证码中断等全部留痕</p>
      <div id="audit"></div>
    </div>
  </section>

  <section class="mod" data-mod="pref">
    <div class="card">
      <h2>个人求职意向</h2>
      <p class="hint">配置期望城市 / 薪资 / 技能 / 岗类，系统按匹配度给在招岗位打分（0-100）</p>

      <div style="margin-bottom:16px">
        <label style="font-size:12.5px;color:var(--muted)">期望城市（多选）</label>
        <div id="prefCities" style="display:flex;flex-wrap:wrap;gap:8px;margin-top:7px"></div>
      </div>

      <div style="margin-bottom:16px;display:flex;gap:16px;flex-wrap:wrap">
        <div>
          <label style="font-size:12.5px;color:var(--muted)">期望月薪（K）</label>
          <div style="margin-top:5px">
            <input id="prefSalMin" type="number" placeholder="下限" style="width:90px;padding:6px 9px;border:1px solid #d5d9e0;border-radius:6px;font-size:13px">
            <span style="color:var(--muted);margin:0 4px">~</span>
            <input id="prefSalMax" type="number" placeholder="上限" style="width:90px;padding:6px 9px;border:1px solid #d5d9e0;border-radius:6px;font-size:13px">
          </div>
        </div>
        <div>
          <label style="font-size:12.5px;color:var(--muted)">期望经验（年）</label>
          <div style="margin-top:5px">
            <input id="prefExpMin" type="number" placeholder="最低" style="width:80px;padding:6px 9px;border:1px solid #d5d9e0;border-radius:6px;font-size:13px">
            <span style="color:var(--muted);margin:0 4px">~</span>
            <input id="prefExpMax" type="number" placeholder="最高" style="width:80px;padding:6px 9px;border:1px solid #d5d9e0;border-radius:6px;font-size:13px">
          </div>
        </div>
      </div>

      <div style="margin-bottom:16px">
        <label style="font-size:12.5px;color:var(--muted)">期望技能（逗号分隔，如 C++, Linux, MySQL）</label>
        <input id="prefSkills" placeholder="C++, Linux, MySQL"
          style="width:100%;margin-top:5px;padding:8px 11px;border:1px solid #d5d9e0;border-radius:8px;font-size:13px;font-family:inherit">
      </div>

      <div style="margin-bottom:18px">
        <label style="font-size:12.5px;color:var(--muted)">期望岗类（多选）</label>
        <div id="prefCats" style="display:flex;flex-wrap:wrap;gap:8px;margin-top:7px"></div>
      </div>

      <div style="display:flex;gap:12px;align-items:center">
        <button onclick="savePref()"
          style="padding:8px 20px;border:none;background:var(--accent);color:#fff;border-radius:8px;cursor:pointer;font-size:13px;font-family:inherit">保存并匹配</button>
        <span id="prefMsg" class="sub"></span>
      </div>
    </div>

    <div class="card">
      <h2>匹配岗位（按匹配度排序）</h2>
      <p class="hint">城市 25 + 薪资 30 + 技能 35（按交集比例）+ 岗类 10 = 总分 100<span class="asof"></span></p>
      <div id="matchList"></div>
    </div>
  </section>

  <section class="mod" data-mod="config">
    <div class="card">
      <h2>采集配置</h2>
      <p class="hint">配置采集的<b>关键词</b>和<b>城市</b>，定时任务按此执行（每组合 30 条/页）</p>

      <div style="margin-bottom:16px">
        <label style="font-size:12.5px;color:var(--muted)">关键词（逗号分隔）</label>
        <input id="planKeywords" placeholder="开发, C++, 前端, 测试, 算法"
          style="width:100%;margin-top:5px;padding:8px 11px;border:1px solid #d5d9e0;border-radius:8px;font-size:13px;font-family:inherit">
      </div>

      <div style="margin-bottom:16px">
        <label style="font-size:12.5px;color:var(--muted)">城市（多选）</label>
        <div id="planCities" style="display:flex;flex-wrap:wrap;gap:8px;margin-top:7px"></div>
      </div>

      <div style="margin-bottom:18px">
        <label style="font-size:12.5px;color:var(--muted)">每个组合抓几页（30 条/页）</label>
        <input id="planPages" type="number" min="1" max="10" value="2"
          style="width:80px;margin-left:10px;padding:6px 9px;border:1px solid #d5d9e0;border-radius:6px;font-size:13px">
      </div>

      <div style="display:flex;gap:12px;align-items:center">
        <button onclick="savePlan()"
          style="padding:8px 20px;border:none;background:var(--accent);color:#fff;border-radius:8px;cursor:pointer;font-size:13px;font-family:inherit">保存配置</button>
        <span id="planMsg" class="sub"></span>
      </div>
      <p class="hint" style="margin-top:14px">
        定时任务（每小时）会读取此配置执行采集。前提：Chrome 9223 常驻且已登录 BOSS。
      </p>
    </div>
  </section>

  </main>
</div>

<div class="statusbar" id="statusbar"><div class="st">状态加载中…</div></div>

<script>
const KEY = new URLSearchParams(location.search).get('key') || '';
const $ = id => document.getElementById(id);

function esc(s){ return String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

// 左侧菜单切换模块
document.getElementById('menu')?.addEventListener('click', e => {
  const btn = e.target.closest('.menu-item');
  if(!btn) return;
  document.querySelectorAll('.menu-item').forEach(t => t.classList.toggle('active', t === btn));
  document.querySelectorAll('.mod').forEach(m => m.classList.toggle('active', m.dataset.mod === btn.dataset.mod));
});
// 底部状态栏（30 秒轮询）
async function loadStatus(){
  try{
    const d = await api('/api/status');
    const last = d.last_scrape_at ? new Date(d.last_scrape_at) : null;
    const mins = last ? Math.round((Date.now() - last.getTime()) / 60000) : null;
    const agoStr = mins == null ? '—' : mins < 1 ? '刚刚'
                 : mins < 60 ? `${mins} 分钟前` : `${Math.floor(mins / 60)} 小时前`;
    const up = d.uptime_seconds || 0;
    const upStr = up >= 3600 ? `${Math.floor(up / 3600)}h ${Math.floor(up % 3600 / 60)}m`
                             : `${Math.floor(up / 60)}m ${up % 60}s`;
    const srcs = d.sources || [];
    const enabled = srcs.filter(x => x.enabled).length;
    // BOSS 账号：真实探测结果（ok=登录有效 / warn=登录异常 / bad=Chrome未启动）
    const ba = d.boss_account || {};
    const baState = ba.state || 'unknown';
    const baDot = baState === 'ok' ? 'ok' : (baState === 'warn' ? 'warn' : 'bad');
    const baText = baState === 'ok' ? '账号 正常'
                 : baState === 'warn' ? `账号 ${ba.detail || '异常'}`
                 : '账号 Chrome未启动';
    $('statusbar').innerHTML =
      `<div class="st"><i class="dot ${d.monitor ? 'ok' : 'bad'}"></i>监控 ${d.monitor ? '运行中' : '已停止'}</div>` +
      `<div class="st">最近采集 ${agoStr}</div>` +
      `<div class="st">运行 ${upStr}</div>` +
      `<div class="st"><i class="dot ${d.network_ok ? 'ok' : 'bad'}"></i>网络 ${d.network_ok ? '在线' : '离线'}</div>` +
      `<div class="st" title="${esc((d.boss_account || {}).detail || '')}"><i class="dot ${baDot}"></i>${baText}</div>` +
      `<div class="st">数据源 ${enabled}/${srcs.length}</div>`;
  }catch(e){
    $('statusbar').innerHTML = '<div class="st"><i class="dot bad"></i>状态获取失败</div>';
  }
}
setInterval(loadStatus, 30000);

// 求职意向
const CAT_OPTIONS = ["后端开发","前端开发","测试","算法/AI","数据","运维/SRE","嵌入式/硬件","网络安全","移动开发"];
async function loadPref(){
  try{
    const d = await api('/api/preference');
    const selC = new Set(d.cities || []);
    $('prefCities').innerHTML = CITY_OPTIONS.map(c =>
      `<label style="display:flex;align-items:center;gap:6px;padding:6px 11px;border:1px solid var(--line);border-radius:8px;cursor:pointer;font-size:12.5px">
        <input type="checkbox" value="${c.name}" ${selC.has(c.name)?'checked':''}> ${c.name}
      </label>`).join('');
    const selCat = new Set(d.categories || []);
    $('prefCats').innerHTML = CAT_OPTIONS.map(c =>
      `<label style="display:flex;align-items:center;gap:6px;padding:6px 11px;border:1px solid var(--line);border-radius:8px;cursor:pointer;font-size:12.5px">
        <input type="checkbox" value="${c}" ${selCat.has(c)?'checked':''}> ${c}
      </label>`).join('');
    $('prefSalMin').value = d.salary_min ?? '';
    $('prefSalMax').value = d.salary_max ?? '';
    $('prefExpMin').value = d.exp_min ?? '';
    $('prefExpMax').value = d.exp_max ?? '';
    $('prefSkills').value = (d.skills || []).join(', ');
  }catch(e){ console.warn('loadPref', e); }
}
async function savePref(){
  const cities = [...$('prefCities').querySelectorAll('input:checked')].map(el => el.value);
  const categories = [...$('prefCats').querySelectorAll('input:checked')].map(el => el.value);
  const skills = $('prefSkills').value.split(/[,，\s]+/).map(x=>x.trim()).filter(Boolean);
  const num = id => { const v = $(id).value.trim(); return v === '' ? null : Number(v); };
  const body = {cities, categories, skills,
    salary_min: num('prefSalMin'), salary_max: num('prefSalMax'),
    exp_min: num('prefExpMin'), exp_max: num('prefExpMax')};
  try{
    const r = await fetch('/api/preference', {method:'PUT',
      headers:{'X-API-Key':KEY,'Content-Type':'application/json'}, body: JSON.stringify(body)});
    const d = await r.json();
    $('prefMsg').textContent = d.ok ? '已保存，正在匹配…' : '保存失败';
    await loadMatch();
    setTimeout(() => { $('prefMsg').textContent = ''; }, 3000);
  }catch(e){ $('prefMsg').textContent = '保存失败: ' + e.message; }
}
async function loadMatch(){
  try{
    const d = await api('/api/match_jobs?limit=20');
    const rows = d.rows || [];
    if(!rows.length){ $('matchList').innerHTML = '<div class="empty">暂无匹配（先保存求职意向）</div>'; return; }
    $('matchList').innerHTML = table(
      [{label:'匹配'},{label:'岗位'},{label:'公司'},{label:'城市'},{label:'月薪'},{label:'来源'},{label:'操作'}],
      rows.map(r => [
        `<b style="color:${r.score>=70?'#0b7a43':r.score>=40?'#9a5b00':'#6b7280'}">${r.score}</b>`,
        esc(r.title_raw),
        esc(r.company_name || '-'),
        esc([r.city, r.district].filter(Boolean).join('·') || '-'),
        fmtSalary(r),
        esc(SOURCE_NAME[r.source_id] || r.source_id || '-'),
        r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">查看 ↗</a>` : '-'
      ]),
      '暂无匹配');
  }catch(e){ $('matchList').innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`; }
}

// 采集配置
const CITY_OPTIONS = [
  {code:"101110100", name:"西安"}, {code:"101270100", name:"成都"},
  {code:"101040100", name:"重庆"}, {code:"101010100", name:"北京"},
  {code:"101020100", name:"上海"}, {code:"101280100", name:"广州"},
  {code:"101280600", name:"深圳"}, {code:"101210100", name:"杭州"},
];
async function loadPlan(){
  try{
    const d = await api('/api/scrape_plan');
    $('planKeywords').value = (d.keywords || []).join(', ');
    $('planPages').value = d.pages_per_combo || 2;
    const selected = new Set((d.cities || []).map(c => c.code));
    $('planCities').innerHTML = CITY_OPTIONS.map(c =>
      `<label style="display:flex;align-items:center;gap:6px;padding:6px 11px;border:1px solid var(--line);border-radius:8px;cursor:pointer;font-size:12.5px">
        <input type="checkbox" value="${c.code}" data-name="${c.name}" ${selected.has(c.code)?'checked':''}> ${c.name}
      </label>`).join('');
  }catch(e){ console.warn('loadPlan', e); }
}
async function savePlan(){
  const keywords = $('planKeywords').value.split(/[,，\s]+/).map(x=>x.trim()).filter(Boolean);
  const cities = [...$('planCities').querySelectorAll('input:checked')].map(el => ({code: el.value, name: el.dataset.name}));
  const pages = parseInt($('planPages').value) || 2;
  try{
    const r = await fetch('/api/scrape_plan', {
      method: 'PUT',
      headers: {'X-API-Key': KEY, 'Content-Type': 'application/json'},
      body: JSON.stringify({source_id:'boss', keywords, cities, pages_per_combo: pages, enabled: true}),
    });
    const d = await r.json();
    $('planMsg').textContent = d.ok ? `已保存（${keywords.length} 词 × ${cities.length} 城）` : '保存失败';
  }catch(e){ $('planMsg').textContent = '保存失败: ' + e.message; }
  setTimeout(() => { $('planMsg').textContent = ''; }, 3000);
}

// 折叠/展开侧边栏
document.getElementById('collapseBtn')?.addEventListener('click', () => {
  document.getElementById('sidebar')?.classList.toggle('collapsed');
});
// 小屏默认折叠
if (window.innerWidth < 900) document.getElementById('sidebar')?.classList.add('collapsed');

async function api(path){
  const r = await fetch(path, {headers:{'X-API-Key': KEY}});
  if(!r.ok) throw new Error(r.status + ' ' + path);
  return r.json();
}

function kpi(label, value, unit){
  return `<div class="kpi"><div class="k">${esc(label)}</div>
    <div class="v">${esc(value)}${unit?`<span class="u">${esc(unit)}</span>`:''}</div></div>`;
}

function hbar(items, color, fmt){
  if(!items.length) return '<div class="empty">暂无数据</div>';
  const max = Math.max(...items.map(i => i[1])) || 1;
  const rowH = 20, w = 520, labelW = 90, valW = 56, pw = w - labelW - valW;
  const h = items.length * rowH + 6;
  let s = `<svg viewBox="0 0 ${w} ${h}" width="100%" style="max-width:560px">`;
  items.forEach(([lab, val], i) => {
    const bh = 7, cy = 3 + i * rowH + (rowH - bh) / 2;
    const bw = Math.max(pw * val / max, 2);
    s += `<text x="${labelW-8}" y="${cy+bh-2}" text-anchor="end" font-size="11" fill="#1f2328">${esc(lab)}</text>`;
    s += `<rect x="${labelW}" y="${cy}" width="${pw}" height="${bh}" rx="3.5" fill="#f2f4f7"/>`;
    s += `<rect x="${labelW}" y="${cy}" width="${bw.toFixed(1)}" height="${bh}" rx="3.5" fill="${color}" opacity="0.9"/>`;
    s += `<text x="${w-4}" y="${cy+bh-2}" text-anchor="end" font-size="11" fill="#6b7280">${esc(fmt?fmt(val):val)}</text>`;
  });
  return s + '</svg>';
}

function vbar(items, color){
  if(!items.length) return '<div class="empty">暂无数据</div>';
  const max = Math.max(...items.map(i => i[1])) || 1;
  const w = 520, h = 210, ml = 6, mb = 26, mt = 14;
  const bw = (w - ml * 2) / items.length;
  let s = `<svg viewBox="0 0 ${w} ${h}" width="100%">`;
  items.forEach(([lab, val], i) => {
    const bh = (h - mb - mt) * val / max;
    const x = ml + i * bw + bw * 0.16;
    const y = h - mb - bh;
    s += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(bw*0.68).toFixed(1)}" height="${bh.toFixed(1)}" rx="3" fill="${color}" opacity="0.85"/>`;
    s += `<text x="${(x+bw*0.34).toFixed(1)}" y="${(y-4).toFixed(1)}" text-anchor="middle" font-size="10" fill="#6b7280">${val}</text>`;
    s += `<text x="${(x+bw*0.34).toFixed(1)}" y="${h-mb+14}" text-anchor="middle" font-size="10" fill="#6b7280">${esc(lab)}</text>`;
  });
  return s + '</svg>';
}

function heatmap(rows, categories, skills){
  if(!rows.length) return '<div class="empty">暂无数据</div>';
  const map = {}; let max = 1;
  rows.forEach(r => { const k = r.category + '|' + r.skill; map[k] = r.n; if(r.n > max) max = r.n; });
  let s = '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:11px">';
  s += '<tr><th style="text-align:left;padding:5px 8px;color:#6b7280;font-weight:500;white-space:nowrap">岗类 \\ 技能</th>';
  skills.forEach(sk => s += `<th style="padding:5px 8px;color:#6b7280;font-weight:500;white-space:nowrap">${esc(sk)}</th>`);
  s += '</tr>';
  categories.forEach(cat => {
    s += `<tr><td style="padding:5px 8px;white-space:nowrap;color:#1f2328">${esc(cat)}</td>`;
    skills.forEach(sk => {
      const n = map[cat + '|' + sk] || 0;
      const a = n ? Math.min(0.12 + 0.88 * n / max, 0.95) : 0;
      const bg = n ? `rgba(47,111,235,${a.toFixed(2)})` : 'transparent';
      s += `<td style="padding:5px 8px;text-align:center;background:${bg};color:${a > 0.5 ? '#fff' : '#1f2328'};border-radius:3px">${n || ''}</td>`;
    });
    s += '</tr>';
  });
  return s + '</table></div>';
}

function line(points){
  if(!points.length) return '<div class="empty">暂无数据</div>';
  const w = 1080, h = 180, ml = 42, mb = 26, mt = 10;
  const pw = w - ml - 12, ph = h - mt - mb;
  const max = Math.max(...points.map(p => p[1])) || 1;
  const step = points.length > 1 ? pw / (points.length - 1) : pw;
  const xy = points.map((p, i) => [ml + i * step, mt + ph - ph * p[1] / max]);
  let s = `<svg viewBox="0 0 ${w} ${h}" width="100%">`;
  for(let i = 0; i <= 3; i++){
    const y = mt + ph * i / 3;
    s += `<line x1="${ml}" y1="${y}" x2="${w-12}" y2="${y}" stroke="#e8eaee"/>`;
    s += `<text x="${ml-8}" y="${y+4}" text-anchor="end" font-size="10" fill="#6b7280">${Math.round(max*(1-i/3))}</text>`;
  }
  s += `<polyline points="${xy.map(p=>p.map(n=>n.toFixed(1)).join(',')).join(' ')}"
        fill="none" stroke="#2f6feb" stroke-width="2" stroke-linejoin="round"/>`;
  xy.forEach((p, i) => {
    s += `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="2.5" fill="#fff" stroke="#2f6feb" stroke-width="2"><title>${esc(points[i][0])}: ${points[i][1]}</title></circle>`;
  });
  const stepLbl = Math.max(1, Math.ceil(points.length / 10));
  points.forEach((p, i) => {
    if(i % stepLbl) return;
    s += `<text x="${xy[i][0].toFixed(1)}" y="${h-8}" text-anchor="middle" font-size="10" fill="#6b7280">${esc(p[0].slice(5))}</text>`;
  });
  return s + '</svg>';
}

function bars(points){
  if(!points.length) return '<div class="empty">暂无数据</div>';
  const w = 1080, h = 200, ml = 46, mr = 12, mt = 12, mb = 28;
  const pw = w - ml - mr, ph = h - mt - mb;
  const max = Math.max(...points.map(p => p[1])) || 1;
  const slot = pw / points.length;
  const bw = Math.min(slot * 0.55, 46);
  let s = `<svg viewBox="0 0 ${w} ${h}" width="100%">`;
  for(let i = 0; i <= 3; i++){
    const y = mt + ph * i / 3;
    s += `<line x1="${ml}" y1="${y}" x2="${w-mr}" y2="${y}" stroke="#e8eaee"/>`;
    s += `<text x="${ml-8}" y="${y+4}" text-anchor="end" font-size="10" fill="#6b7280">${Math.round(max*(1-i/3))}</text>`;
  }
  const stepLbl = Math.max(1, Math.ceil(points.length / 14));
  points.forEach((p, i) => {
    const bh = ph * p[1] / max;
    const x = ml + slot * i + (slot - bw) / 2, y = mt + ph - bh;
    s += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}"
          height="${Math.max(bh,1).toFixed(1)}" rx="3" fill="#2f6feb" opacity="0.9">
          <title>${esc(p[0])}: ${p[1]}</title></rect>`;
    if(points.length <= 14)
      s += `<text x="${(x+bw/2).toFixed(1)}" y="${(y-5).toFixed(1)}" text-anchor="middle"
            font-size="10" fill="#1f2328">${p[1]}</text>`;
    if(i % stepLbl === 0)
      s += `<text x="${(x+bw/2).toFixed(1)}" y="${h-8}" text-anchor="middle"
            font-size="10" fill="#6b7280">${esc(p[0].slice(5))}</text>`;
  });
  return s + '</svg>';
}

function table(headers, rows, empty){
  if(!rows.length) return `<div class="empty">${esc(empty || '暂无数据')}</div>`;
  const th = headers.map(h => `<th class="${h.num?'num':''}">${esc(h.label)}</th>`).join('');
  const tb = rows.map(r => '<tr>' + r.map((c, i) =>
    `<td class="${headers[i].num?'num':''}">${c}</td>`).join('') + '</tr>').join('');
  return `<table><thead><tr>${th}</tr></thead><tbody>${tb}</tbody></table>`;
}

// 薪资统一显示为 K（库里的 salary_min/max 对 month 单位即为千元；对 day/hour 为元）
function fmtSalary(r){
  // 完全无法结构化：面议 / 空
  if(!r.salary_ok || (r.salary_min == null && r.salary_max == null)){
    if(r.salary_raw && r.salary_raw.indexOf('面议') >= 0) return '面议';
    return esc(r.salary_raw || '-');
  }
  const k = v => {                              // 千元 -> 保留 1 位小数，去 .0
    const n = Math.round(Number(v) * 10) / 10;
    return String(n);
  };
  const isMonth = (r.salary_unit || 'month') === 'month';
  if(!isMonth){                                 // 日薪 / 时薪：按「元」显示
    const v = r.salary_min != null ? r.salary_min : r.salary_max;
    let body = (r.salary_min != null && r.salary_max != null && r.salary_min !== r.salary_max)
      ? `${r.salary_min}-${r.salary_max}元` : `${v}元`;
    body += (r.salary_min != null && r.salary_max == null) ? '以上'
          : (r.salary_max != null && r.salary_min == null) ? '以下' : '';
    return esc(body);
  }
  let body;
  if(r.salary_min != null && r.salary_max != null && r.salary_min !== r.salary_max){
    body = `${k(r.salary_min)}-${k(r.salary_max)}K`;
  } else if(r.salary_min != null && r.salary_max == null){
    body = `${k(r.salary_min)}K以上`;
  } else if(r.salary_max != null && r.salary_min == null){
    body = `${k(r.salary_max)}K以下`;
  } else {
    body = `${k(r.salary_min != null ? r.salary_min : r.salary_max)}K`;
  }
  const months = r.salary_months && r.salary_months > 12 ? ` · ${r.salary_months}薪` : '';
  return esc(body + months);
}

// 岗位来源显示名（source_id -> 中文）
const SOURCE_NAME = {boss: 'BOSS直聘', mohrss: '中国公共招聘网', company: '公司官网'};

const JOB_PAGE = 20;
let jobOffset = 0, jobTotal = 0;

async function loadJobs(offset){
  jobOffset = Math.max(0, offset || 0);
  const p = new URLSearchParams({limit: JOB_PAGE, offset: jobOffset});
  const cat = $('fCat').value, city = $('fCity').value,
        q = $('fQ').value.trim(), sort = $('fSort').value;
  if(cat) p.set('category', cat);
  if(city) p.set('city', city);
  if(q) p.set('q', q);
  if(sort) p.set('sort', sort);
  try{
    const d = await api('/api/jobs?' + p.toString());
    jobTotal = d.total;
    $('jobCount').textContent = `共 ${d.total} 条`;
    $('jobList').innerHTML = table(
      [{label:'岗位'},{label:'公司'},{label:'城市'},{label:'月薪'},{label:'来源'},{label:'发布/采集'},{label:'操作'}],
      d.rows.map(r => [
        esc(r.title_raw),
        esc(r.company_name || '-'),
        esc([r.city, r.district].filter(Boolean).join('·') || '-'),
        fmtSalary(r),
        esc(SOURCE_NAME[r.source_id] || r.source_id || '-'),
        r.posted_at
          ? esc(String(r.posted_at).slice(0, 10))
          : (r.first_seen ? `采集 ${esc(String(r.first_seen).slice(5, 16).replace('T', ' '))}` : '-'),
        r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">查看详情 ↗</a>` : '-'
      ]),
      '没有符合条件的岗位');
    $('pageInfo').textContent =
      `${Math.floor(jobOffset / JOB_PAGE) + 1} / ${Math.max(1, Math.ceil(jobTotal / JOB_PAGE))}`;
    $('prevBtn').disabled = jobOffset <= 0;
    $('nextBtn').disabled = jobOffset + JOB_PAGE >= jobTotal;
  }catch(e){
    $('jobList').innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`;
  }
}

function pageJobs(delta){ loadJobs(jobOffset + delta * JOB_PAGE); }

async function triggerRun(id){
  if(!confirm('立即采集 ' + id + '？约需 60~90 秒，期间运行历史里会看到 running。')) return;
  const r = await fetch(`/api/sources/${id}/run`, {method:'POST', headers:{'X-API-Key':KEY}});
  if(r.status === 202){ alert('已接受，后台执行中。约 1 分钟后刷新本页。'); }
  else if(r.status === 409){ alert('该源正在运行中（或已停用），请稍后刷新。'); }
  else { alert('触发失败：' + r.status + ' ' + (await r.text())); }
}

async function main(){
  if(!KEY){
    $('banner').innerHTML = '<div class="err">缺少访问密钥：请在地址后加 <code>?key=你的密钥</code>。'
      + '密钥即启动服务时的 <code>JOBMVP_API_KEY</code>。</div>';
    $('sub').textContent = '未认证';
    return;
  }
  try{
    const [sources, quality, activeR, dailyR, salaryR, runs, unmapped, audit, jobsR, skillsR, domainsR, metaR, salaryHistR, expR, skillMatrixR] = await Promise.all([
      api('/api/sources'), api('/api/quality'),
      api('/api/metrics/active_jobs?limit=2000'),
      api('/api/metrics/new_jobs_daily?limit=2000'),
      api('/api/metrics/salary_by_category?limit=2000'),
      api('/api/sources/mohrss/runs?limit=8'),
      api('/api/unmapped?limit=10'),
      api('/api/audit?limit=10'),
      api('/api/jobs?limit=1'),
      api('/api/analytics/skills?limit=15'),
      api('/api/analytics/domains'),
      api('/api/analytics/meta'),
      api('/api/analytics/salary_hist?step=5'),
      api('/api/analytics/experience'),
      api('/api/analytics/skill_matrix?top=8'),
    ]);

    // 指标接口返回 {metric, version, rows}
    const active = activeR.rows || [], daily = dailyR.rows || [], salary = salaryR.rows || [];
    const src = sources[0] || {};
    const q = quality[0] || {};
    const last = src.last_run || {};

    $('sub').innerHTML = `数据源 <b>${esc(src.name || '-')}</b>
      <span class="pill ${src.enabled?'ok':'bad'}">${src.enabled?'已启用':'已停用'}</span>
      <span class="pill">${esc(src.tier || '-')} 级</span>`;
    const dedupTotal = jobsR.total ?? 0;
    // 数据时效：最新采集时间
    const asOf = metaR && metaR.data_as_of ? new Date(metaR.data_as_of) : null;
    const pad2 = n => String(n).padStart(2, '0');
    const asOfStr = asOf
      ? `${asOf.getMonth() + 1}-${asOf.getDate()} ${pad2(asOf.getHours())}:${pad2(asOf.getMinutes())}`
      : '-';
    document.querySelectorAll('.asof').forEach(el => { el.textContent = `（截至 ${asOfStr}）`; });
    $('meta').textContent = `在招 ${dedupTotal} 条（已去重）· 数据截至 ${asOfStr}`;

    $('kpis').innerHTML =
      kpi('在招岗位', dedupTotal.toLocaleString(), '条') +
      kpi('薪资可解析率', q.salary_parse_pct ?? '-', '%') +
      kpi('地区匹配率', q.region_match_pct ?? '-', '%') +
      kpi('岗类映射率', q.category_map_pct ?? '-', '%');

    $('quality').innerHTML = [
      ['薪资解析', q.salary_parse_pct], ['地区匹配', q.region_match_pct],
      ['岗类映射', q.category_map_pct], ['技能命中', q.skill_hit_pct],
    ].map(([k, v]) => `<div style="margin-bottom:9px">
        <div style="display:flex;justify-content:space-between;font-size:12px">
          <span>${k}</span><span style="color:#6b7280">${v ?? '-'}%</span></div>
        <div class="bar"><i style="width:${Math.min(v ?? 0, 100)}%"></i></div></div>`).join('');

    $('sources').innerHTML = sources.map(s => `<div style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div><b>${esc(s.name)}</b> <span class="pill">${esc(s.source_id)}</span>
          <span class="pill ${s.tier==='A'?'ok':'warn'}">${esc(s.tier)} 级</span></div>
        <span class="pill ${s.enabled?'ok':'bad'}">${s.enabled?'enabled':'disabled'}</span>
        <button onclick="triggerRun('${esc(s.source_id)}')"
          style="margin-left:8px;padding:3px 10px;border:1px solid #d5d9e0;background:#fff;
          border-radius:7px;font-size:12px;cursor:pointer">立即采集</button>
      </div>
      <div class="sub" style="margin-top:4px">间隔 ${esc(s.min_interval_s)}s ·
        ${s.last_run ? `上次 ${esc(s.last_run.status)} · 解析 ${s.last_run.parsed} 条 ·
        ${esc((s.last_run.finished_at||'').slice(0,19).replace('T',' '))}` : '尚未运行'}</div>
      </div>`).join('') || '<div class="empty">无数据源</div>';

    const byDay = {};
    daily.forEach(r => { byDay[r.day] = (byDay[r.day] || 0) + r.new_jobs; });
    const days = Object.entries(byDay).sort();
    $('trend').innerHTML = bars(days)
      + (days.length === 1 ? '<div class="empty" style="padding-top:8px">'
         + '目前只有一次采集，趋势需要多次运行后才有意义。</div>' : '');

    const fam = {}, city = {};
    active.forEach(r => {
      const k = r.category || '未映射';
      fam[k] = (fam[k] || 0) + r.active_jobs;
      const c = r.city || '未知';
      city[c] = (city[c] || 0) + r.active_jobs;
    });
    const sortDesc = o => Object.entries(o).sort((a, b) => b[1] - a[1]);
    $('families').innerHTML = hbar(sortDesc(fam).slice(0, 10), '#2f6feb');

    const skills = (skillsR.rows || []).map(r => [r.skill, r.n]);
    $('skills').innerHTML = hbar(skills, '#7c3aed');
    const domains = (domainsR.rows || []).map(r => [r.domain, r.n]);
    $('domains').innerHTML = hbar(domains, '#0891b2');

    // 薪资分布直方图（月薪区间）
    const hist = (salaryHistR.rows || []).map(r => [`${r.lo}-${r.lo + 5}`, r.n]);
    $('salaryHist').innerHTML = vbar(hist, '#2f6feb');

    // 经验要求分布
    const exp = (expR.rows || []).map(r => [r.bucket, r.n]);
    $('expDist').innerHTML = hbar(exp, '#0891b2');

    // 技能 × 岗类矩阵
    const mrows = skillMatrixR.rows || [];
    const mcats = [...new Set(mrows.map(r => r.category))];
    const mskills = [...new Set(mrows.map(r => r.skill))];
    $('skillMatrix').innerHTML = heatmap(mrows, mcats, mskills);
    $('cities').innerHTML = hbar(sortDesc(city).slice(0, 10), '#12a594');

    $('salary').innerHTML = table(
      [{label:'岗类'},{label:'样本',num:1},
       {label:'P25',num:1},{label:'P50',num:1},{label:'P75',num:1}],
      salary.map(r => [esc(r.category), r.n,
        Number(r.p25_k).toFixed(1) + 'K', Number(r.p50_k).toFixed(1) + 'K',
        Number(r.p75_k).toFixed(1) + 'K']),
      '暂无可展示岗类（样本需 ≥ 30）');

    $('runs').innerHTML = table(
      [{label:'开始时间'},{label:'状态'},{label:'抓取',num:1},{label:'解析',num:1},{label:'失败',num:1}],
      runs.map(r => [esc((r.started_at||'').slice(5,19).replace('T',' ')),
        `<span class="pill ${r.status==='success'?'ok':'bad'}">${esc(r.status)}</span>`,
        r.fetched, r.parsed, r.parse_failed]));

    $('unmapped').innerHTML = table(
      [{label:'岗位名'},{label:'次数',num:1}],
      unmapped.map(r => [esc(r.term), r.cnt]), '没有未映射项');

    $('fCat').innerHTML = '<option value="">全部岗类</option>' +
      sortDesc(fam).map(([k]) => k).filter(k => k !== '未映射')
        .map(k => `<option>${esc(k)}</option>`).join('');
    $('fCity').innerHTML = '<option value="">全部城市</option>' +
      sortDesc(city).map(([k]) => k).filter(k => k !== '未知')
        .map(k => `<option>${esc(k)}</option>`).join('');
    loadJobs(0);
    loadPlan();
    loadPref();
    loadStatus();
    loadMatch();

    $('audit').innerHTML = table(
      [{label:'时间'},{label:'动作'},{label:'对象'},{label:'操作者'}],
      audit.map(r => [esc((r.at||'').slice(5,19).replace('T',' ')),
        `<span class="pill">${esc(r.action)}</span>`, esc(r.target||'-'), esc(r.actor)]));
  }catch(e){
    $('banner').innerHTML = `<div class="err">加载失败：${esc(e.message)}
      （密钥是否正确？服务是否在运行？）</div>`;
  }
}
main();
</script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def index() -> str:
    return INDEX_HTML
