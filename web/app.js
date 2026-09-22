/* AI Platform 사내 콘솔 — 인증 가드 + 권한별 nav + 섹션 렌더. envelope({ok,data,meta}) 기준. */

// nav = 그룹 트리. module=null은 공통(항상), 그 외는 config.enabled_modules에 켜져야 표시.
// 각 항목은 권한(perm)도 있어야 보임. 그룹에 볼 항목이 없으면 그룹째 숨김.
const NAV = [
  { group: '공통', module: null, items: [
    { id: 'usage', label: '사용량',   ico: '💰', perm: 'usage:read' },
    { id: 'logs',  label: '접근 로그', ico: '📈', perm: 'logs:read' },
    { id: 'users', label: '유저 관리', ico: '👥', perm: 'users:manage' },
  ] },
  { group: 'OCR', module: 'ocr', items: [
    { id: 'ocrtest', label: 'OCR 테스트', ico: '🧪', perm: 'ocr:test' },
    { id: 'ocrhist', label: '테스트 이력', ico: '📜', perm: 'ocr:test' },
  ] },
  { group: '추천', module: 'recommend', items: [
    { id: 'rectest', label: '추천 테스트', ico: '🎯', perm: 'recommend:test' },
  ] },
  { group: '전결규정', module: 'approval', items: [
    { id: 'apvtest', label: '전결규정 테스트', ico: '📋', perm: 'approval:test' },
  ] },
];

// ── helpers ──
const $ = id => document.getElementById(id);
const val = id => $(id).value.trim();
const emptyRow = n => `<tr><td colspan="${n}" class="empty">데이터 없음</td></tr>`;
const escapeHtml = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const fmtTs = s => {           // UTC ISO → 브라우저 로컬(KST) 표시
  try { return s ? new Date(s).toLocaleString('sv-SE').slice(0, 19) : '-'; }
  catch { return s || '-'; }
};
const stClass = s => s >= 500 ? 'st-5xx' : s >= 400 ? 'st-4xx' : 'st-2xx';
function toast(msg, kind) {
  const el = document.createElement('div');
  el.className = 'toast ' + (kind || 'ok'); el.textContent = msg;
  $('toasts').appendChild(el); setTimeout(() => el.remove(), 3000);
}

async function api(path, opts = {}) {
  const res = await fetch(path, { credentials: 'same-origin', ...opts });
  let json = null; try { json = await res.json(); } catch {}
  if (res.status === 401) { location.href = '/login'; throw new Error('unauth'); }
  if (!json || !json.ok) throw new Error(json?.error?.message || ('HTTP ' + res.status));
  return json.data;
}

// ── nav / sections ──
let me = null;

async function init() {
  try { me = await api('/auth/me'); }
  catch { location.href = '/login'; return; }

  $('whoName').textContent = me.username;
  $('whoRole').textContent = me.role;
  const perms = new Set(me.permissions || []);
  const has = p => perms.has('*') || perms.has(p);

  let enabled = new Set();
  try { enabled = new Set((await api('/core/modules')).enabled || []); } catch { /* 실패시 공통만 */ }

  const flat = [];
  let html = '';
  NAV.forEach(g => {
    if (g.module && !enabled.has(g.module)) return;         // 꺼진 모듈 그룹 숨김
    const items = g.items.filter(s => has(s.perm));
    if (!items.length) return;                              // 볼 항목 없으면 그룹째 숨김
    html += `<div class="nav-group">${g.group}</div>`;
    items.forEach(s => {
      flat.push(s);
      html += `<a data-sec="${s.id}"><span class="ico">${s.ico}</span>${s.label}</a>`;
    });
  });
  $('nav').innerHTML = html;
  $('nav').querySelectorAll('a').forEach(a =>
    a.addEventListener('click', () => showSection(a.dataset.sec)));

  if (flat.length) showSection(flat[0].id);
  else document.querySelector('.content').innerHTML = '<div class="empty">접근 가능한 화면이 없습니다.</div>';
}

function showSection(id) {
  document.querySelectorAll('.content section').forEach(s => s.hidden = true);
  $('sec-' + id).hidden = false;
  document.querySelectorAll('#nav a').forEach(a => a.classList.toggle('active', a.dataset.sec === id));
  const labels = { ocrtest: 'OCR 테스트', ocrhist: '테스트 이력', rectest: '추천 테스트', apvtest: '전결규정 테스트', usage: '사용량', logs: '접근 로그', users: '유저 관리' };
  $('pageTitle').textContent = labels[id];
  const loaders = { ocrtest: loadOcrTest, ocrhist: loadOcrHistory, rectest: loadRecTest, apvtest: loadApvTest, usage: loadUsage, logs: loadLogs, users: loadUsers };
  loaders[id]().catch(e => toast(e.message, 'err'));
}

// ── 전결규정 테스트 ──
async function loadApvTest() {
  try {
    const c = await api('/approval/test/collections');
    const def = c.default || 'APPROVAL_RULE';
    $('av-collection').innerHTML = (c.collections || []).map(x =>
      `<option value="${escapeHtml(x)}"${x === def ? ' selected' : ''}>${escapeHtml(x)}</option>`).join('')
      || `<option value="${escapeHtml(def)}">${escapeHtml(def)}</option>`;
  } catch (e) {
    $('av-collection').innerHTML = '<option value="APPROVAL_RULE">APPROVAL_RULE</option>';
    toast(e.message, 'err');
  }
  $('av-run').onclick = runApvTest;
}

async function runApvTest() {
  const q = $('av-query').value.trim();
  if (!q) { toast('질문(QUERY_TEXT)을 입력하세요', 'err'); return; }
  const filters = {};
  const put = (k, id) => { const v = $(id).value.trim(); if (v) filters[k] = v; };
  put('BUKRS', 'av-bukrs'); put('CATEGORY', 'av-category');
  put('REQUESTER_GROUP', 'av-requester'); put('AMOUNT_KRW', 'av-amount');
  if ($('av-doctype').value) filters.DOCUMENT_TYPE = $('av-doctype').value;
  if ($('av-ruletype').value) filters.RULE_TYPE = $('av-ruletype').value;
  const body = { QUERY_TEXT: q, COLLECTION: $('av-collection').value, TOP_K: 5, FILTERS: filters };

  const btn = $('av-run'); btn.disabled = true;
  $('av-status').textContent = '검색 중…'; $('av-result').innerHTML = '';
  try {
    const res = await fetch('/approval/test', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (res.status === 401) { location.href = '/login'; return; }
    const json = await res.json();
    if (!json.ok) throw new Error(json.error?.message || ('HTTP ' + res.status));
    renderApvTest(json.data);
    $('av-status').textContent = '완료';
  } catch (e) {
    toast(e.message, 'err'); $('av-status').textContent = '실패';
  } finally { btn.disabled = false; }
}

function renderApvTest(data) {
  const items = data.ITEMS || [];
  const msg = data.META?.MESSAGE;
  if (!items.length) {
    $('av-result').innerHTML = `<div class="empty">${escapeHtml(msg || '일치하는 규정이 없습니다.')}</div>`;
    return;
  }
  const amt = a => {
    if (!a) return '-';
    const lo = a.MIN_KRW != null ? `${a.MIN_KRW}${a.MIN_INCLUSIVE ? '≤' : '<'}` : '';
    const hi = a.MAX_KRW != null ? `${a.MAX_INCLUSIVE ? '≤' : '<'}${a.MAX_KRW}` : '';
    return (lo || hi) ? `${lo} 금액 ${hi}` : '-';
  };
  $('av-result').innerHTML = `
    <div class="muted" style="margin-bottom:10px">${items.length}건 · MIN_SCORE ${data.META?.MIN_SCORE ?? ''} · ${data.ELAPSED}s</div>
    ${items.map(it => `
      <div class="card" style="margin-bottom:12px">
        <div class="card-head" style="display:flex;justify-content:space-between;align-items:center">
          <span>${escapeHtml(it.RULE_TYPE || '')} · ${escapeHtml(it.CONDITIONS?.CATEGORY || '')}</span>
          <span class="st-2xx">${it.SIMILARITY}%</span>
        </div>
        <div class="card-body">
          <div style="line-height:1.6;margin-bottom:10px">${escapeHtml(it.TEXT?.PASSAGE || '')}</div>
          <div class="mono muted" style="font-size:11px;line-height:1.7">
            결재선: ${escapeHtml(it.OUTPUT?.APPROVAL_LINE_REQUIRED || '-')} · 승인자: ${escapeHtml((it.OUTPUT?.APPROVER_CODES || []).join(', ') || '-')}<br>
            기안자군: ${escapeHtml(it.CONDITIONS?.REQUESTER_GROUP || '-')} · ${escapeHtml(amt(it.CONDITIONS?.AMOUNT))}<br>
            ${escapeHtml(it.DOCUMENT_TYPE || '')} · ${escapeHtml(it.DOC_NAME || '')} · RULE_ID ${escapeHtml(it.RULE_ID || '')}
          </div>
        </div>
      </div>`).join('')}`;
}

// ── 추천 테스트 ──
const FIT_LABEL = { '1': ['추천', 'st-2xx'], '2': ['검토', 'st-4xx'], '3': ['미추천', 'st-5xx'] };

async function loadRecTest() {
  try {
    const c = await api('/recommend/test/collections');
    $('rt-collection').innerHTML = '<option value="">(form_type 자동)</option>' +
      (c.collections || []).map(x => `<option value="${escapeHtml(x)}">${escapeHtml(x)}</option>`).join('');
  } catch (e) {
    $('rt-collection').innerHTML = '<option value="">(form_type 자동)</option>';
    toast(e.message, 'err');
  }
  $('rt-run').onclick = runRecTest;
}

async function runRecTest() {
  const merch = $('rt-merch').value.trim();
  if (!merch) { toast('가맹점명을 입력하세요', 'err'); return; }
  const q = { MERCH_NAME: merch };
  const mcc = $('rt-mcc').value.trim(); if (mcc) q.MCC_NAME = mcc;
  const body = { form_type: $('rt-formtype').value, queries: [q] };
  const col = $('rt-collection').value; if (col) body.collection = col;

  const btn = $('rt-run'); btn.disabled = true;
  $('rt-status').textContent = '추천 중…'; $('rt-result').innerHTML = '';
  try {
    const res = await fetch('/recommend/test', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (res.status === 401) { location.href = '/login'; return; }
    const json = await res.json();
    if (!json.ok) throw new Error(json.error?.message || ('HTTP ' + res.status));
    renderRecTest(json.data, json.meta.usage);
    $('rt-status').textContent = '완료';
  } catch (e) {
    toast(e.message, 'err'); $('rt-status').textContent = '실패';
  } finally { btn.disabled = false; }
}

function renderRecTest(data, u) {
  const r = (data.results || [])[0];
  if (!r) { $('rt-result').innerHTML = '<div class="empty">결과 없음</div>'; return; }
  const [flabel, fclass] = FIT_LABEL[r.FIT_FLAG] || ['-', 'muted'];
  const cands = (r.ALL_RECOMMENDATIONS || []).map((c, i) => `
    <tr><td>${i + 1}</td><td class="mono">${escapeHtml(c.HKONT || '')}</td>
      <td>${escapeHtml(c.HKONT_TXT || '')}</td><td class="mono">${c.SCORE}</td>
      <td class="mono muted">${c.SCORE_DETAIL ? `sim ${c.SCORE_DETAIL.MAX_SIM} · freq ${c.FREQUENCY ?? '-'}` : ''}</td></tr>`).join('');
  $('rt-result').innerHTML = `
    <div class="summary">
      <div class="sc accent"><div class="l">추천 계정</div><div class="v" style="font-size:18px">${escapeHtml(r.HKONT || '-')}</div></div>
      <div class="sc"><div class="l">점수</div><div class="v">${r.SCORE}</div></div>
      <div class="sc"><div class="l">판정</div><div class="v" style="font-size:16px"><span class="${fclass}">${flabel}</span> <span class="muted" style="font-size:11px">${r.CONFIDENCE || ''}</span></div></div>
      <div class="sc"><div class="l">경과</div><div class="v">${u.ms}ms</div></div>
    </div>
    <div class="card" style="margin-bottom:14px"><div class="card-head">추천 · ${escapeHtml(r.HKONT_TXT || '')}</div>
      <div class="card-body">
        <div class="mono muted" style="margin-bottom:8px">쿼리: ${escapeHtml(r.query_text || '')}</div>
        <div style="line-height:1.6">${escapeHtml(r.FIT_REASON || '')}</div>
      </div></div>
    <div class="card"><div class="card-head">후보 (ALL_RECOMMENDATIONS)</div>
      <div class="tbl-wrap"><table class="tbl">
        <thead><tr><th>#</th><th>계정</th><th>계정명</th><th>점수</th><th>상세</th></tr></thead>
        <tbody>${cands || emptyRow(5)}</tbody></table></div></div>`;
}

// ── 테스트 이력 ──
let histRuns = [];                  // 이력 원본 (표·비교 공용)
let cmpGroups = [];                 // 비교뷰 그룹 목록 (인덱스로 체크박스 참조)
const CMP_COLORS = ['#16a34a', '#ef4444', '#3b82f6', '#f59e0b', '#9b59b6', '#1abc9c', '#e67e22'];

async function loadOcrHistory() {
  histRuns = (await api('/ocr/test/history')).runs || [];
  $('histTable').innerHTML = `
    <thead><tr>
      <th style="width:30px"><input type="checkbox" id="hist-all" title="전체 선택"></th>
      <th>시각</th><th>실행자</th><th>그룹</th><th>모델</th><th>종류</th><th>파일</th>
      <th>페이지(성공/전체)</th><th>wall</th><th>work</th><th>토큰</th><th></th></tr></thead>
    <tbody>${histRuns.map(r => `<tr data-id="${r.id}" style="cursor:pointer">
      <td><input type="checkbox" class="hist-cb" value="${r.id}"></td>
      <td class="mono">${fmtTs(r.ts)}</td><td>${escapeHtml(r.username || '-')}</td>
      <td>${escapeHtml(r.group_name || '-')}</td>
      <td class="mono">${escapeHtml(r.model || '-')}</td><td>${escapeHtml(r.doc_type || '-')}</td>
      <td>${r.file_count ?? '-'}</td><td>${r.ok_count}/${r.page_count}</td>
      <td class="mono">${secs(r.wall_ms)}</td><td class="mono">${secs(r.work_ms)}</td>
      <td class="mono">${r.total_tokens ?? '-'}</td>
      <td><button class="btn btn-sm btn-danger hist-del">삭제</button></td></tr>`).join('') || emptyRow(12)}</tbody>`;

  const all = $('hist-all');
  if (all) all.onchange = () => $('histTable').querySelectorAll('.hist-cb').forEach(cb => cb.checked = all.checked);
  $('histTable').querySelectorAll('tr[data-id]').forEach(tr => {
    tr.addEventListener('click', e => {
      if (e.target.closest('.hist-cb, .hist-del')) return;      // 체크·삭제 클릭은 상세 열지 않음
      showHistDetail(tr.dataset.id);
    });
    tr.querySelector('.hist-del').addEventListener('click', () => deleteRuns([+tr.dataset.id]));
  });
  $('hist-del-sel').onclick = () => deleteRuns(
    [...$('histTable').querySelectorAll('.hist-cb:checked')].map(cb => +cb.value));
  $('hist-refresh').onclick = loadOcrHistory;
  $('hist-view-table').onclick = () => histView('table');
  $('hist-view-compare').onclick = () => histView('compare');
  $('hist-detail').innerHTML = '';
  if (!$('hist-compare-view').hidden) renderCompare();   // 비교뷰 유지 중이면 갱신
}

function histView(mode) {
  const cmp = mode === 'compare';
  $('hist-table-view').hidden = cmp;
  $('hist-compare-view').hidden = !cmp;
  $('hist-view-table').classList.toggle('btn-primary', !cmp);
  $('hist-view-compare').classList.toggle('btn-primary', cmp);
  if (cmp) renderCompare();
}

// ── 비교 뷰 ──
function renderCompare() {
  cmpGroups = [...new Set(histRuns.map(r => r.group_name || '미지정'))];
  $('cmp-groups').innerHTML = cmpGroups.length
    ? cmpGroups.map((g, i) => `<label style="display:inline-flex;align-items:center;gap:6px;margin:0 16px 8px 0;cursor:pointer">
        <input type="checkbox" class="cmp-cb" data-i="${i}" checked> ${escapeHtml(g)}</label>`).join('')
    : '<div class="muted">그룹이 없습니다. 테스트 실행 시 그룹명을 지정하세요.</div>';
  $('cmp-groups').querySelectorAll('.cmp-cb').forEach(cb => cb.onchange = drawCompare);
  $('cmp-metric').onchange = drawCompare;
  drawCompare();
}

// 지표별 값 추출·표기 설정
const CMP_METRICS = {
  wall:   { get: r => (r.wall_ms || 0) / 1000, unit: 's', dec: 2, label: '실제 경과(초)' },
  work:   { get: r => (r.work_ms || 0) / 1000, unit: 's', dec: 2, label: '모델시간(초)' },
  tokens: { get: r => r.total_tokens || 0,     unit: '',  dec: 0, label: '토큰 수' },
};

function drawCompare() {
  const conf = CMP_METRICS[$('cmp-metric').value] || CMP_METRICS.wall;
  const sel = [...$('cmp-groups').querySelectorAll('.cmp-cb:checked')].map(cb => cmpGroups[+cb.dataset.i]);
  const series = sel.map((g, i) => {
    const runs = histRuns.filter(r => (r.group_name || '미지정') === g).sort((a, b) => a.id - b.id);
    return { name: g, color: CMP_COLORS[i % CMP_COLORS.length], vals: runs.map(conf.get) };
  });
  $('cmp-chart').innerHTML = series.length ? svgLineChart(series, conf) : '<div class="empty">그룹을 선택하세요.</div>';
  $('cmp-stats').innerHTML = series.filter(s => s.vals.length).map(s => {
    const n = s.vals.length, avg = s.vals.reduce((a, b) => a + b, 0) / n;
    return `<div class="sc" style="border-left:4px solid ${s.color}">
      <div class="l">${escapeHtml(s.name)}</div>
      <div class="v" style="font-size:17px">${avg.toFixed(conf.dec)}${conf.unit} <span class="muted" style="font-size:11px">평균</span></div>
      <div class="muted" style="font-size:11px;margin-top:4px">${n}건 · 최소 ${Math.min(...s.vals).toFixed(conf.dec)} · 최대 ${Math.max(...s.vals).toFixed(conf.dec)}</div>
    </div>`;
  }).join('') || '';
}

function svgLineChart(series, conf) {
  const W = 720, H = 320, pad = { l: 50, r: 16, t: 16, b: 34 };
  const fmt = v => v.toFixed(conf.dec) + conf.unit;
  const maxLen = Math.max(1, ...series.map(s => s.vals.length));
  const maxY = Math.max(1, ...series.flatMap(s => s.vals));
  const yTop = Math.max(1, maxY * 1.1);
  const X = i => pad.l + (maxLen <= 1 ? (W - pad.l - pad.r) / 2 : (i / (maxLen - 1)) * (W - pad.l - pad.r));
  const Y = v => H - pad.b - (v / yTop) * (H - pad.t - pad.b);
  const grid = [0, .25, .5, .75, 1].map(f => { const v = yTop * f; return `<line x1="${pad.l}" y1="${Y(v)}" x2="${W - pad.r}" y2="${Y(v)}" stroke="var(--border-light)"/><text x="${pad.l - 6}" y="${Y(v) + 3}" text-anchor="end" font-size="10" fill="var(--text-muted)">${v.toFixed(conf.dec)}</text>`; }).join('');
  const xlab = Array.from({ length: maxLen }, (_, i) => `<text x="${X(i)}" y="${H - pad.b + 16}" text-anchor="middle" font-size="10" fill="var(--text-muted)">${i + 1}</text>`).join('');
  const lines = series.map(s => {
    if (!s.vals.length) return '';
    const pts = s.vals.map((v, i) => `${X(i)},${Y(v)}`).join(' ');
    const dots = s.vals.map((v, i) => `<circle cx="${X(i)}" cy="${Y(v)}" r="3" fill="${s.color}"><title>${escapeHtml(s.name)} #${i + 1}: ${fmt(v)}</title></circle>`).join('');
    return `<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="2"/>${dots}`;
  }).join('');
  const legend = series.map(s => `<span style="display:inline-flex;align-items:center;gap:5px;margin-right:14px;font-size:12px"><span style="width:14px;height:3px;background:${s.color};display:inline-block"></span>${escapeHtml(s.name)}</span>`).join('');
  return `<div style="overflow-x:auto"><svg viewBox="0 0 ${W} ${H}" style="width:100%;min-width:520px">
    <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${H - pad.b}" stroke="var(--border-color)"/>
    <line x1="${pad.l}" y1="${H - pad.b}" x2="${W - pad.r}" y2="${H - pad.b}" stroke="var(--border-color)"/>
    ${grid}${xlab}${lines}</svg></div>
    <div style="margin-top:8px">${legend}</div>
    <div class="muted" style="font-size:11px;margin-top:4px">X축 = 그룹 내 실행 순서 · Y축 = ${conf.label}. 같은 순서끼리 비교하려면 각 그룹에서 같은 파일을 같은 순서로 실행하세요.</div>`;
}

async function deleteRuns(ids) {
  if (!ids.length) { toast('선택된 항목이 없습니다', 'err'); return; }
  if (!confirm(`이력 ${ids.length}개를 삭제할까요?`)) return;
  try {
    await api('/ocr/test/history/delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    });
    toast('삭제되었습니다', 'ok');
    loadOcrHistory();
  } catch (e) { toast(e.message, 'err'); }
}

async function showHistDetail(id) {
  const run = await api('/ocr/test/history/' + id);
  $('hist-detail').innerHTML = `
    <div class="card"><div class="card-head">실행 #${run.id} · ${escapeHtml(run.model || '')} · ${escapeHtml(run.doc_type || '')} · ${fmtTs(run.ts)}</div>
      <div class="card-body">${run.result ? filesHtml(run.result) : '<div class="empty">결과 없음</div>'}</div></div>`;
  $('hist-detail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// ── OCR 테스트 (요청을 여러 개 추가 — 각각 파일·설정 독립) ──
let otModels = null;   // {models, default}  (한 번만 로드)
let otIdx = 0;         // 요청 카드 번호
let otInited = false;  // 섹션 재진입 시 카드/바인딩 유지

const fmtBytes = n => n < 1024 ? n + ' B'
  : n < 1048576 ? (n / 1024).toFixed(1) + ' KB'
  : (n / 1048576).toFixed(1) + ' MB';
const secs = ms => (ms == null ? '-' : (ms / 1000).toFixed(1) + 's');

async function refreshGroupDatalist() {
  try {
    const g = await api('/ocr/test/groups');
    $('ot-groups').innerHTML = (g.groups || []).map(x => `<option value="${escapeHtml(x)}">`).join('');
  } catch { /* 그룹 없음 무시 */ }
}

async function loadOcrTest() {
  if (otInited) return;                       // 이미 초기화됐으면 상태 유지(탭 전환해도 요청 보존)
  otModels = await api('/ocr/test/models');
  refreshGroupDatalist();
  $('ot-add').onclick = () => addRequestCard();
  $('ot-run-all').onclick = runAllRequests;
  // 카드 내부 요소는 위임으로 처리(카드가 동적 추가돼도 바인딩 유지)
  $('ot-requests').addEventListener('change', e => {
    if (e.target.classList.contains('ot-files')) renderFileListIn(e.target.closest('.ot-req'));
  });
  $('ot-requests').addEventListener('click', e => {
    const card = e.target.closest('.ot-req'); if (!card) return;
    if (e.target.classList.contains('ot-run')) runRequest(card);
    else if (e.target.classList.contains('ot-del')) removeCard(card);
    else if (e.target.classList.contains('ot-more')) {
      const resEl = card.querySelector('.ot-result');
      e.target.textContent = resEl.classList.toggle('clamp') ? '더보기' : '접기';
    }
  });
  addRequestCard();                           // 시작 시 요청 1개
  otInited = true;
}

function requestCardHtml(idx) {
  const opts = otModels.models.map(m =>
    `<option value="${m}"${m === otModels.default ? ' selected' : ''}>${m}</option>`).join('');
  return `<div class="card ot-req" data-idx="${idx}">
    <div class="card-head" style="display:flex;justify-content:space-between;align-items:center">
      <span>요청 #${idx}</span>
      <button class="btn btn-sm btn-danger ot-del" type="button">삭제</button>
    </div>
    <div class="card-body">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
        <div class="field" style="margin-bottom:8px"><label>문서 종류</label>
          <select class="inp ot-doctype">
            <option value="auto">⚡ 자동 분류</option>
            <option value="card">카드/현금영수증</option>
            <option value="jiro">지로영수증</option>
            <option value="tax">세금계산서</option>
          </select></div>
        <div class="field" style="margin-bottom:8px"><label>모델</label>
          <select class="inp ot-model">${opts}</select></div>
      </div>
      <div class="field" style="margin-bottom:8px"><label>그룹 (비교용, 선택)</label>
        <input class="inp ot-group" list="ot-groups" placeholder="예: vertex / 원본100"></div>
      <div class="field" style="margin-bottom:8px"><label>파일 (여러 개 · 이미지·PDF)</label>
        <input class="inp ot-files" type="file" multiple accept="image/*,application/pdf"></div>
      <div class="ot-filelist" style="margin-bottom:12px"></div>
      <div style="display:flex;align-items:center;gap:12px">
        <button class="btn btn-primary ot-run" type="button">실행</button>
        <span class="muted ot-status"></span>
      </div>
      <div class="summary ot-summary ot-sum" style="margin-top:14px"></div>
      <div class="ot-result"></div>
      <button class="btn btn-sm ot-more" type="button" hidden>더보기</button>
    </div>
  </div>`;
}

function addRequestCard() {
  otIdx += 1;
  $('ot-requests').insertAdjacentHTML('beforeend', requestCardHtml(otIdx));
}

function removeCard(card) {
  if ($('ot-requests').querySelectorAll('.ot-req').length <= 1) {
    toast('최소 1개 요청은 필요합니다', 'err'); return;
  }
  card.remove();
}

function setupClamp(card) {                    // 결과가 캡을 넘으면 접고 '더보기' 노출
  const resEl = card.querySelector('.ot-result');
  const moreBtn = card.querySelector('.ot-more');
  resEl.classList.add('clamp');
  if (resEl.scrollHeight > resEl.clientHeight + 4) {
    moreBtn.hidden = false; moreBtn.textContent = '더보기';
  } else {
    resEl.classList.remove('clamp'); moreBtn.hidden = true;   // 안 넘치면 캡 해제
  }
}

function renderFileListIn(card) {
  const files = [...card.querySelector('.ot-files').files];
  const box = card.querySelector('.ot-filelist');
  if (!files.length) { box.innerHTML = ''; return; }
  const total = files.reduce((a, f) => a + f.size, 0);
  box.innerHTML = `
    <div class="tbl-wrap"><table class="tbl">
      <thead><tr><th>#</th><th>파일명</th><th>형식</th><th>크기</th></tr></thead>
      <tbody>${files.map((f, i) => `<tr>
        <td>${i + 1}</td><td>${escapeHtml(f.name)}</td>
        <td class="mono muted">${escapeHtml(f.type || '-')}</td>
        <td class="mono">${fmtBytes(f.size)}</td></tr>`).join('')}</tbody>
    </table></div>
    <div class="muted" style="margin-top:6px">${files.length}개 · 합계 ${fmtBytes(total)}</div>`;
}

function setCardDisabled(card, on) {          // 호출 중 카드 조작 잠금(버튼·셀렉트·파일)
  card.querySelectorAll('button, select, input').forEach(el => { el.disabled = on; });
  card.style.opacity = on ? '0.7' : '';
}

async function runRequest(card) {
  const files = [...card.querySelector('.ot-files').files];
  if (!files.length) { toast('파일을 선택하세요', 'err'); return; }
  const model = card.querySelector('.ot-model').value;
  const docType = card.querySelector('.ot-doctype').value;
  const group = card.querySelector('.ot-group').value.trim();
  const status = card.querySelector('.ot-status'); status.textContent = '처리 중…';
  const sumEl = card.querySelector('.ot-summary'); const resEl = card.querySelector('.ot-result');
  sumEl.innerHTML = ''; resEl.innerHTML = '';
  card.querySelector('.ot-more').hidden = true; resEl.classList.remove('clamp');
  setCardDisabled(card, true);

  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  fd.append('model', model); fd.append('doc_type', docType); fd.append('group', group);
  try {
    const res = await fetch('/ocr/test', { method: 'POST', credentials: 'same-origin', body: fd });
    if (res.status === 401) { location.href = '/login'; return; }
    const json = await res.json();
    if (!json.ok) throw new Error(json.error?.message || ('HTTP ' + res.status));
    sumEl.innerHTML = summaryHtml(json.meta.usage);
    resEl.innerHTML = filesHtml(json.data);
    setupClamp(card);                           // 결과 길면 접고 '더보기' 노출
    status.textContent = '완료';
    if (group) refreshGroupDatalist();          // 새 그룹이면 자동완성에 반영
  } catch (e) {
    toast(e.message, 'err'); status.textContent = '실패';
  } finally { setCardDisabled(card, false); }
}

function runAllRequests() {
  const cards = [...$('ot-requests').querySelectorAll('.ot-req')]
    .filter(c => c.querySelector('.ot-files').files.length);
  if (!cards.length) { toast('파일이 선택된 요청이 없습니다', 'err'); return; }
  cards.forEach(runRequest);                  // 각 요청 동시 발사(각자 독립)
}

function summaryHtml(u) {
  return `
    <div class="sc accent"><div class="l">실제 경과 (wall)</div><div class="v">${secs(u.wall_ms)}</div></div>
    <div class="sc"><div class="l">모델시간 합 (work)</div><div class="v">${secs(u.work_ms)}</div></div>
    <div class="sc"><div class="l">페이지 (성공/전체)</div><div class="v">${u.ok_count}/${u.pages}</div></div>
    <div class="sc"><div class="l">토큰</div><div class="v">${u.tokens.total_tokens}</div></div>`;
}

function filesHtml(data) {
  return data.files.map(f => `
    <div class="card" style="margin:12px 0">
      <div class="card-head" style="display:flex;justify-content:space-between;align-items:center">
        <span>📄 ${escapeHtml(f.filename)}</span>
        <span class="${f.ok ? 'st-2xx' : 'st-5xx'}">${f.ok ? '성공' : '실패'} · ${f.page_count}p</span>
      </div>
      <div class="card-body">
        ${f.pages.map(p => `
          <div style="margin-bottom:12px">
            <div class="mono muted" style="margin-bottom:5px">
              p${p.page_index} · <b>${p.doc_type ?? '분류실패'}</b> · ${p.ms ?? '-'}ms
              ${p.ok ? '' : `· <span class="st-5xx">${escapeHtml(p.error || '실패')}</span>`}
            </div>
            ${p.ok ? `<pre class="ot-json">${escapeHtml(JSON.stringify(p.result, null, 2))}</pre>` : ''}
          </div>`).join('')}
      </div>
    </div>`).join('') || '<div class="empty">결과 없음</div>';
}

// ── 사용량 ──
async function loadUsage() {
  const fEl = $('usage-filter');
  if (fEl) fEl.onchange = loadUsage;                         // 필터 바꾸면 재렌더
  const mode = fEl?.value || 'real';
  const isInternal = t => (t || '').startsWith('__');        // '__' 접두사 = 테스트/내부 구분자
  let rows = (await api('/core/usage')).rollup || [];
  if (mode === 'real') rows = rows.filter(r => !isInternal(r.tenant));
  else if (mode === 'test') rows = rows.filter(r => isInternal(r.tenant));
  const tReq = rows.reduce((a, r) => a + r.requests, 0);
  const tQty = rows.reduce((a, r) => a + r.quantity, 0);
  const tenants = new Set(rows.map(r => r.tenant)).size;
  $('usageSummary').innerHTML = `
    <div class="sc accent"><div class="l">총 수량</div><div class="v">${tQty}</div></div>
    <div class="sc"><div class="l">총 요청</div><div class="v">${tReq}</div></div>
    <div class="sc"><div class="l">고객사 수</div><div class="v">${tenants}</div></div>`;
  $('usageTable').innerHTML =
    `<thead><tr><th>고객사</th><th>기능</th><th>provider</th><th>수량</th><th>요청</th><th>성공</th></tr></thead><tbody>${
      rows.map(r => `<tr><td>${r.tenant}</td><td>${r.feature}</td><td class="mono">${r.provider}</td>
        <td>${r.quantity}</td><td>${r.requests}</td><td>${r.ok_count}</td></tr>`).join('') || emptyRow(6)
    }</tbody>`;
}

// ── 접근 로그 ──
async function loadLogs() {
  const rows = (await api('/core/logs')).logs || [];
  $('logsTable').innerHTML =
    `<thead><tr><th>시각</th><th>method</th><th>path</th><th>status</th><th>ms</th></tr></thead><tbody>${
      rows.map(r => `<tr><td class="mono">${fmtTs(r.ts)}</td><td class="mono">${r.method}</td>
        <td class="mono">${r.path}</td><td class="${stClass(r.status)}">${r.status}</td><td>${r.ms}</td></tr>`).join('') || emptyRow(5)
    }</tbody>`;
}

// ── 유저 관리 ──
async function loadUsers() {
  const rows = (await api('/admin/users')).users || [];
  const t = $('usersTable');
  t.innerHTML =
    `<thead><tr><th>아이디</th><th>역할</th><th>상태</th><th>생성</th><th></th></tr></thead><tbody>${
      rows.map(u => `<tr>
        <td>${u.username}</td>
        <td><span class="role-badge">${u.role}</span></td>
        <td>${u.is_active ? '<span class="st-2xx">활성</span>' : '<span class="st-5xx">비활성</span>'}</td>
        <td class="mono muted">${fmtTs(u.created_at)}</td>
        <td><button class="btn btn-sm ${u.is_active ? 'btn-danger' : 'btn-primary'}"
             data-uid="${u.id}" data-act="${u.is_active ? 0 : 1}">${u.is_active ? '비활성화' : '활성화'}</button></td>
      </tr>`).join('') || emptyRow(5)
    }</tbody>`;
  t.querySelectorAll('button[data-uid]').forEach(b => b.addEventListener('click', async () => {
    try {
      await api('/admin/users/' + b.dataset.uid, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: b.dataset.act === '1' }),
      });
      toast('변경되었습니다', 'ok'); loadUsers();
    } catch (e) { toast(e.message, 'err'); }
  }));
}

// ── 정적 버튼 바인딩 (항상 존재) ──
$('newUserBtn').addEventListener('click', () => { const c = $('newUserCard'); c.hidden = !c.hidden; });
$('nu-save').addEventListener('click', async () => {
  try {
    await api('/admin/users', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: val('nu-username'), password: val('nu-password'), role: val('nu-role') }),
    });
    toast('유저가 생성되었습니다', 'ok');
    $('newUserCard').hidden = true;
    $('nu-username').value = ''; $('nu-password').value = '';
    loadUsers();
  } catch (e) { toast(e.message, 'err'); }
});
$('logoutBtn').addEventListener('click', async () => {
  await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' });
  location.href = '/login';
});
$('themeBtn').addEventListener('click', () => {
  const next = (document.documentElement.getAttribute('data-theme') || 'light') === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
});

init();
