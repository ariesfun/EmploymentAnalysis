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
<title>招聘市场数据控制台</title>
<style>
:root{--ink:#1f2328;--muted:#6b7280;--line:#e6e8ec;--bg:#f6f7f9;--card:#fff;
--accent:#2f6feb;--ok:#0f9d58;--warn:#d97706;--bad:#d92d20}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.6;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 20px 60px}
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
.err{background:#fdeceb;border:1px solid #f5c6c2;color:#b3261e;padding:10px 14px;
border-radius:10px;font-size:12.5px;margin-bottom:14px}
code{background:#f2f4f7;padding:1px 5px;border-radius:4px;font-size:12px}
svg{display:block}
footer{margin-top:22px;text-align:center;color:#9aa1ab;font-size:11.5px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>招聘市场数据控制台</h1>
      <div class="sub" id="sub">加载中…</div>
    </div>
    <div class="sub" id="meta"></div>
  </header>
  <div id="banner"></div>

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

  <div class="grid g2">
    <div class="card">
      <h2>岗类分布（在招）</h2>
      <p class="hint">未映射岗位显示为「未映射」，进 unmapped_term 队列</p>
      <div id="families"></div>
    </div>
    <div class="card">
      <h2>城市分布（在招）</h2>
      <p class="hint">按标准化后的地级市统计</p>
      <div id="cities"></div>
    </div>
  </div>

  <div class="card">
    <h2>薪资分位（P25 / P50 / P75）</h2>
    <p class="hint">仅 status=active 且 salary_ok 且 salary_unit=month；分组样本 &lt; 30 不输出</p>
    <div id="salary"></div>
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

  <footer>jobmvp console · 指标口径 v1</footer>
</div>

<script>
const KEY = new URLSearchParams(location.search).get('key') || '';
const $ = id => document.getElementById(id);

function esc(s){ return String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

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
  const rowH = 24, w = 520, labelW = 96, valW = 70, pw = w - labelW - valW;
  const h = items.length * rowH + 8;
  let s = `<svg viewBox="0 0 ${w} ${h}" width="100%">`;
  items.forEach(([lab, val], i) => {
    const y = 4 + i * rowH, bh = rowH - 10;
    const bw = Math.max(pw * val / max, 2);
    s += `<text x="${labelW-8}" y="${y+bh/2+4}" text-anchor="end" font-size="11" fill="#1f2328">${esc(lab)}</text>`;
    s += `<rect x="${labelW}" y="${y}" width="${pw}" height="${bh}" rx="3" fill="#f2f4f7"/>`;
    s += `<rect x="${labelW}" y="${y}" width="${bw.toFixed(1)}" height="${bh}" rx="3" fill="${color}" opacity="0.88"/>`;
    s += `<text x="${w-4}" y="${y+bh/2+4}" text-anchor="end" font-size="11" fill="#6b7280">${esc(fmt?fmt(val):val)}</text>`;
  });
  return s + '</svg>';
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
    const [sources, quality, activeR, dailyR, salaryR, runs, unmapped, audit] = await Promise.all([
      api('/api/sources'), api('/api/quality'),
      api('/api/metrics/active_jobs?limit=2000'),
      api('/api/metrics/new_jobs_daily?limit=2000'),
      api('/api/metrics/salary_pctl?limit=2000'),
      api('/api/sources/mohrss/runs?limit=8'),
      api('/api/unmapped?limit=10'),
      api('/api/audit?limit=10'),
    ]);

    // 指标接口返回 {metric, version, rows}
    const active = activeR.rows || [], daily = dailyR.rows || [], salary = salaryR.rows || [];
    const src = sources[0] || {};
    const q = quality[0] || {};
    const last = src.last_run || {};

    $('sub').innerHTML = `数据源 <b>${esc(src.name || '-')}</b>
      <span class="pill ${src.enabled?'ok':'bad'}">${src.enabled?'已启用':'已停用'}</span>
      <span class="pill">${esc(src.tier || '-')} 级</span>`;
    $('meta').textContent = `样本 ${q.total ?? 0} 条 · 指标口径 v1`;

    $('kpis').innerHTML =
      kpi('在招岗位', (q.total ?? 0).toLocaleString(), '条') +
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
    $('cities').innerHTML = hbar(sortDesc(city).slice(0, 10), '#12a594');

    $('salary').innerHTML = table(
      [{label:'岗类'},{label:'城市'},{label:'样本',num:1},
       {label:'P25',num:1},{label:'P50',num:1},{label:'P75',num:1}],
      salary.map(r => [esc(r.category || '未映射'), esc(r.city || '-'), r.n,
        Number(r.p25_k).toFixed(1) + 'K', Number(r.p50_k).toFixed(1) + 'K',
        Number(r.p75_k).toFixed(1) + 'K']),
      '暂无可展示分组（分组样本需 ≥ 30）');

    $('runs').innerHTML = table(
      [{label:'开始时间'},{label:'状态'},{label:'抓取',num:1},{label:'解析',num:1},{label:'失败',num:1}],
      runs.map(r => [esc((r.started_at||'').slice(5,19).replace('T',' ')),
        `<span class="pill ${r.status==='success'?'ok':'bad'}">${esc(r.status)}</span>`,
        r.fetched, r.parsed, r.parse_failed]));

    $('unmapped').innerHTML = table(
      [{label:'岗位名'},{label:'次数',num:1}],
      unmapped.map(r => [esc(r.term), r.cnt]), '没有未映射项');

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
