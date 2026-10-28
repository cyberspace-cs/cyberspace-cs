// 飞书式 IM 演示前端（原生 JS，无框架）。
// 重点演示：会话红点（水位线）+ 单条消息已读回执（谁读了 / X/Y 已读）。

const $ = (id) => document.getElementById(id);

// 兼容部署在 /im 子路径：根据当前路径推导 API / WS 前缀
function basePath() {
  const p = location.pathname.replace(/\/[^/]*$/, '');
  return p === '' ? '' : p;
}
const WS_URL = (location.protocol === 'https:' ? 'wss' : 'ws') +
  '://' + location.host + basePath() + '/ws';
const api = (path) => basePath() + '/api/' + path;

const state = {
  uid: 0,
  ws: null,
  convs: {},        // conv_id -> conversation view
  active: 0,
  msgs: {},         // conv_id -> [message]
  receipts: {},     // msg_id -> {readers, read_count, total}
};

// ---------- 网络 ----------
function login() {
  state.uid = parseInt($('uid').value, 10);
  if (state.ws) state.ws.close();
  state.ws = new WebSocket(WS_URL);
  state.ws.onopen = () => {
    setStatus(true);
    state.ws.send(JSON.stringify({ type: 'login', uid: state.uid }));
  };
  state.ws.onclose = () => setStatus(false);
  state.ws.onmessage = (e) => handle(JSON.parse(e.data));
}

function setStatus(on) {
  const s = $('status');
  s.textContent = on ? '已连接' : '未连接';
  s.className = 'status ' + (on ? 'on' : 'off');
}

function handle(env) {
  switch (env.type) {
    case 'welcome': refreshConvs(); break;
    case 'ack': onAck(env.data); break;
    case 'message': onMessage(env.data); break;
    case 'unread': onUnread(env.data); break;
    case 'receipt': onReceipt(env.data); break;
  }
}

// ---------- 渲染 ----------
async function refreshConvs() {
  const r = await fetch(api('conversations?uid=' + state.uid));
  const list = await r.json();
  state.convs = {};
  list.forEach((c) => (state.convs[c.conv_id] = c));
  renderConvList();
  if (!state.active && list.length) openConv(list[0].conv_id);
}

function renderConvList() {
  const el = $('convList');
  el.innerHTML = '';
  Object.values(state.convs).forEach((c) => {
    const div = document.createElement('div');
    div.className = 'conv' + (c.conv_id === state.active ? ' active' : '');
    const name = c.type === 2 ? (c.title || '群聊') : '单聊 #' + c.conv_id;
    div.innerHTML = `<div><div class="title">${name}</div>
      <div class="meta">成员 ${c.member_cnt} · seq≤${c.latest_seq}</div></div>
      ${c.unread > 0 ? `<span class="badge">${c.unread}</span>` : ''}`;
    div.onclick = () => openConv(c.conv_id);
    el.appendChild(div);
  });
}

async function openConv(convId) {
  state.active = convId;
  const c = state.convs[convId];
  $('chatHead').textContent = (c.type === 2 ? (c.title || '群聊') : '单聊') +
    (c.is_big ? '（超大群·回执降级）' : '');
  const r = await fetch(api(`messages?conv_id=${convId}&before_seq=999999999&limit=50`));
  state.msgs[convId] = await r.json();
  renderMessages();
  $('msgInput').disabled = false;
  $('sendBtn').disabled = false;
  // 打开即「已读」：推进水位线，触发服务端给发送者回执
  sendRead(convId, c.latest_seq);
  renderConvList();
}

function renderMessages() {
  const box = $('messages');
  box.innerHTML = '';
  (state.msgs[state.active] || []).forEach((m) => box.appendChild(renderMsg(m)));
  box.scrollTop = box.scrollHeight;
}

function renderMsg(m) {
  const div = document.createElement('div');
  div.className = 'msg' + (m.sender_uid === state.uid ? ' me' : '');
  const who = m.sender_uid === state.uid ? '我' : ('用户' + m.sender_uid);
  let html = `<div class="who">${who} · #${m.seq}</div>${escapeHtml(m.content)}`;
  if (m.sender_uid === state.uid) {
    const rc = state.receipts[m.msg_id];
    const txt = rc ? `已读 ${rc.read_count}/${rc.total}` + (rc.readers.length ? '（' + rc.readers.map(u => '👤' + u).join(' ') + '）' : '') : '已送达';
    html += `<div class="receipt">${txt}</div>`;
  }
  div.innerHTML = html;
  return div;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// ---------- WS 事件 ----------
function onAck(d) {
  const c = state.active;
  state.msgs[c] = state.msgs[c] || [];
  state.msgs[c].push(d.message);
  if (c === state.active) renderMessages();
}

function onMessage(m) {
  if (m.conv_id === state.active) {
    state.msgs[m.conv_id].push(m);
    renderMessages();
    sendRead(m.conv_id, m.seq); // 收到即读，给发送者回执
  } else {
    refreshConvs(); // 非当前会话，刷新红点
  }
}

function onUnread(d) {
  if (state.convs[d.conv_id]) {
    state.convs[d.conv_id].read_seq = d.read_seq;
    state.convs[d.conv_id].unread = d.unread;
    renderConvList();
  }
}

function onReceipt(r) {
  state.receipts[r.msg_id] = { readers: r.readers, read_count: r.read_count, total: r.total };
  // 更新事件日志 + 当前会话渲染
  const line = `用户 ${r.readers[r.readers.length - 1]} 已读消息 #${r.msg_id}（${r.read_count}/${r.total}）`;
  const log = $('eventLog');
  const d = document.createElement('div');
  d.textContent = line;
  log.prepend(d);
  if (r.conv_id === state.active) renderMessages();
}

// ---------- 发送 ----------
function sendRead(convId, seq) {
  state.ws.send(JSON.stringify({ type: 'read', conv_id: convId, seq }));
}
function send() {
  const txt = $('msgInput').value.trim();
  if (!txt || !state.ws) return;
  state.ws.send(JSON.stringify({ type: 'send', conv_id: state.active, content: txt, client_id: 'c' + Date.now() }));
  $('msgInput').value = '';
}

// ---------- 绑定 ----------
$('loginBtn').onclick = login;
$('sendBtn').onclick = send;
$('msgInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
