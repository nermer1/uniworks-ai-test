/* AI Platform 사내 콘솔 — 인증 가드 + 권한별 nav + 섹션 렌더. envelope({ok,data,meta}) 기준. */

const SECTIONS = [
  { id: 'usage', label: '사용량',   ico: '💰', perm: 'usage:read' },
  { id: 'logs',  label: '접근 로그', ico: '📈', perm: 'logs:read' },
  { id: 'users', label: '유저 관리', ico: '👥', perm: 'users:manage' },
];

// ── helpers ──
const $ = id => document.getElementById(id);
const val = id => $(id).value.trim();
const emptyRow = n => `<tr><td colspan="${n}" class="empty">데이터 없음</td></tr>`;
const fmtTs = s => s ? String(s).replace('T', ' ').slice(0, 19) : '-';
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

  const visible = SECTIONS.filter(s => has(s.perm));
  $('nav').innerHTML = visible.map(s =>
    `<a data-sec="${s.id}"><span class="ico">${s.ico}</span>${s.label}</a>`).join('');
  $('nav').querySelectorAll('a').forEach(a =>
    a.addEventListener('click', () => showSection(a.dataset.sec)));

  if (visible.length) showSection(visible[0].id);
  else document.querySelector('.content').innerHTML = '<div class="empty">접근 가능한 화면이 없습니다.</div>';
}

function showSection(id) {
  document.querySelectorAll('.content section').forEach(s => s.hidden = true);
  $('sec-' + id).hidden = false;
  document.querySelectorAll('#nav a').forEach(a => a.classList.toggle('active', a.dataset.sec === id));
  const labels = { usage: '사용량', logs: '접근 로그', users: '유저 관리' };
  $('pageTitle').textContent = labels[id];
  const loaders = { usage: loadUsage, logs: loadLogs, users: loadUsers };
  loaders[id]().catch(e => toast(e.message, 'err'));
}

// ── 사용량 ──
async function loadUsage() {
  const rows = (await api('/core/usage')).rollup || [];
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
    `<thead><tr><th>시각(UTC)</th><th>method</th><th>path</th><th>status</th><th>ms</th></tr></thead><tbody>${
      rows.map(r => `<tr><td class="mono">${fmtTs(r.ts)}</td><td class="mono">${r.method}</td>
        <td class="mono">${r.path}</td><td class="${stClass(r.status)}">${r.status}</td><td>${r.ms}</td></tr>`).join('') || emptyRow(5)
    }</tbody>`;
}

// ── 유저 관리 ──
async function loadUsers() {
  const rows = (await api('/admin/users')).users || [];
  const t = $('usersTable');
  t.innerHTML =
    `<thead><tr><th>아이디</th><th>역할</th><th>상태</th><th>생성(UTC)</th><th></th></tr></thead><tbody>${
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
