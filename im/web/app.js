// cyberspace-cs 飞书式 IM 前端（原生 JS，无框架）。
// 演示重点：会话红点（水位线）+ 单条消息已读回执（谁读了 / X/Y 已读，可点开看详情）。

const $ = (id) => document.getElementById(id);

// 飞书风格头像配色：按 uid 取色，显示姓名首字（更贴近飞书默认头像）
const PALETTE = ['#3370FF', '#34C724', '#FF8800', '#F5222D', '#7F3BF5',
  '#0FC6C2', '#FF6A00', '#14C9C9', '#F766C6', '#5B8FF9'];
const colorFor = (uid) => PALETTE[Math.abs(uid) % PALETTE.length];

function avatarEl(uid, name, cls = '') {
  const a = document.createElement('div');
  a.className = 'avatar ' + cls;
  a.style.background = colorFor(uid);
  a.textContent = (name || ('#' + uid)).trim().charAt(0).toUpperCase();
  a.title = name || ('用户' + uid);
  return a;
}

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
  users: {},        // uid -> {uid,name,avatar}
  convs: {},        // conv_id -> conversation view
  active: 0,
  msgs: {},         // conv_id -> [message]
  receipts: {},     // msg_id -> {readers, read_count, total}
  members: {},      // conv_id -> [user]
};

// ---------- 工具 ----------
const escapeHtml = (s) => String(s).replace(/[&<>"]/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmtTime = (t) => {
  const d = new Date(t);
  if (isNaN(d)) return '';
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
};
const nameOf = (uid) => (state.users[uid] ? state.users[uid].name : ('用户' + uid));

// ---------- 登录 ----------
function renderLoginUsers() {
  const box = $('loginUsers');
  box.innerHTML = '';
  Object.values(state.users).forEach((u) => {
    const card = document.createElement('div');
    card.className = 'user-card';
    card.appendChild(avatarEl(u.uid, u.name, 'sm'));
    const info = document.createElement('div');
    info.innerHTML = `<div style="font-weight:600">${escapeHtml(u.name)}</div>
      <div style="font-size:11px;color:var(--fs-text-3)">uid ${u.uid}</div>`;
    card.appendChild(info);
    card.onclick = () => doLogin(u.uid);
    box.appendChild(card);
  });
}

function doLogin(uid) {
  state.uid = uid;
  $('loginOverlay').hidden = true;
  $('app').hidden = false;
  // 导航栏右下角头像
  const me = $('railMe');
  me.textContent = (state.users[uid] ? state.users[uid].name : '').charAt(0).toUpperCase();
  me.title = '当前身份：' + nameOf(uid) + '（点击切换）';
  connectWS();
  refreshConvs();
}

function connectWS() {
  if (state.ws) state.ws.close();
  state.ws = new WebSocket(WS_URL);
  state.ws.onopen = () => state.ws.send(JSON.stringify({ type: 'login', uid: state.uid }));
  state.ws.onclose = () => { /* 教学演示不自动重连 */ };
  state.ws.onmessage = (e) => handle(JSON.parse(e.data));
}

// ---------- 网络：REST ----------
async function getJSON(path) {
  const r = await fetch(api(path));
  return r.json();
}

// ---------- WS 事件分发 ----------
function handle(env) {
  switch (env.type) {
    case 'welcome': refreshConvs(); break;
    case 'ack': onAck(env.data); break;
    case 'message': onMessage(env.data); break;
    case 'unread': onUnread(env.data); break;
    case 'receipt': onReceipt(env.data); break;
  }
}

// ---------- 渲染：会话列表 ----------
async function refreshConvs() {
  const list = await getJSON('conversations?uid=' + state.uid);
  state.convs = {};
  list.forEach((c) => (state.convs[c.conv_id] = c));
  renderConvList();
  if (!state.active && list.length) openConv(list[0].conv_id);
}

function renderConvList() {
  const el = $('convList');
  el.innerHTML = '';
  const kw = $('convSearch').value.trim().toLowerCase();
  Object.values(state.convs)
    .filter((c) => !kw || (c.title || '').toLowerCase().includes(kw))
    .forEach((c) => {
      const div = document.createElement('div');
      div.className = 'conv' + (c.conv_id === state.active ? ' active' : '');
      const wrap = document.createElement('div');
      wrap.className = 'avatar-wrap';
      wrap.appendChild(avatarEl(c.conv_id, c.type === 2 ? (c.title || '群') : nameOf(c.last_sender_uid), 'sm'));
      const info = document.createElement('div');
      info.className = 'conv-info';
      const name = c.type === 2 ? (c.title || '群聊') : nameOf(c.last_sender_uid || c.conv_id);
      const preview = c.last_content
        ? (c.last_sender_uid === state.uid ? '我：' : '') + c.last_content
        : (c.type === 2 ? '群聊' : '单聊');
      info.innerHTML = `<div class="conv-name">${escapeHtml(name)}</div>
        <div class="conv-preview">${escapeHtml(preview)}</div>`;
      const right = document.createElement('div');
      right.className = 'conv-right';
      if (c.unread > 0) {
        const b = document.createElement('span');
        b.className = 'badge';
        b.textContent = c.unread > 99 ? '99+' : c.unread;
        right.appendChild(b);
      }
      div.appendChild(wrap);
      div.appendChild(info);
      div.appendChild(right);
      div.onclick = () => openConv(c.conv_id);
      el.appendChild(div);
    });
}

// ---------- 渲染：聊天区 ----------
async function openConv(convId) {
  state.active = convId;
  const c = state.convs[convId];
  $('chatName').textContent = c.type === 2 ? (c.title || '群聊') : nameOf(c.last_sender_uid || convId);
  $('chatMeta').textContent = c.type === 2 ? `${c.member_cnt} 人` : '单聊';
  // 加载成员（用于头像、回执详情）
  try {
    state.members[convId] = await getJSON('members?conv_id=' + convId);
    renderHeadAvatars();
  } catch (e) { /* ignore */ }
  const msgs = await getJSON(`messages?conv_id=${convId}&before_seq=999999999&limit=50`);
  state.msgs[convId] = msgs;
  renderMessages();
  renderMemberPanel();
  $('msgInput').disabled = false;
  $('sendBtn').disabled = false;
  $('composerTip').textContent = c.is_big ? '超大群：已降级，仅推进红点、不维护精确单条回执'
    : '消息已开启单条已读回执（飞书式）';
  sendRead(convId, c.latest_seq); // 打开即已读 -> 触发服务端给发送者回执
  renderConvList();
}

function renderHeadAvatars() {
  const box = $('headAvatars');
  box.innerHTML = '';
  (state.members[state.active] || []).slice(0, 4).forEach((u) =>
    box.appendChild(avatarEl(u.uid, u.name, 'xs')));
}

function renderMessages() {
  const box = $('messages');
  box.innerHTML = '';
  const list = state.msgs[state.active] || [];
  if (!list.length) {
    box.innerHTML = '<div class="empty-hint">还没有消息，发送第一条吧～</div>';
    return;
  }
  list.forEach((m) => box.appendChild(renderMsg(m)));
  box.scrollTop = box.scrollHeight;
}

function renderMsg(m) {
  const me = m.sender_uid === state.uid;
  const row = document.createElement('div');
  row.className = 'msg' + (me ? ' me' : '');

  const av = avatarEl(m.sender_uid, nameOf(m.sender_uid));
  const col = document.createElement('div');
  col.className = 'msg-col';

  if (!me) {
    const nm = document.createElement('div');
    nm.className = 'msg-name';
    nm.textContent = nameOf(m.sender_uid);
    col.appendChild(nm);
  }
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = m.content;
  col.appendChild(bubble);

  // 自己的消息：已读回执行
  if (me) col.appendChild(renderReceiptLine(m));

  row.appendChild(av);
  row.appendChild(col);
  return row;
}

function renderReceiptLine(m) {
  const rc = state.receipts[m.msg_id];
  const line = document.createElement('div');
  line.className = 'receipt-line';
  if (rc && rc.read_count > 0) {
    line.classList.add('read');
    line.innerHTML = `已读 ${rc.read_count}/${rc.total}`;
    const avs = document.createElement('span');
    avs.className = 'receipt-avatars';
    rc.readers.slice(0, 5).forEach((u) => avs.appendChild(avatarEl(u, nameOf(u), 'xs')));
    line.appendChild(avs);
    line.title = '点击查看谁已读';
    line.onclick = () => openReceiptModal(m.conv_id, m.msg_id);
  } else {
    line.textContent = '已送达';
  }
  return line;
}

// ---------- 已读回执详情弹窗 ----------
async function openReceiptModal(convId, msgId) {
  const rc = await getJSON(`receipt?conv_id=${convId}&msg_id=${msgId}`);
  const readers = new Set(rc.readers || []);
  const members = state.members[convId] || [];
  const sender = (state.msgs[convId] || []).find((x) => x.msg_id === msgId);
  const senderUID = sender ? sender.sender_uid : 0;

  $('receiptTitle').textContent = `已读详情（${rc.read_count}/${rc.total}）`;
  const body = $('receiptBody');
  body.innerHTML = '';
  const readList = members.filter((u) => readers.has(u.uid));
  const unreadList = members.filter((u) => u.uid !== senderUID && !readers.has(u.uid));

  const section = (title, arr) => {
    if (!arr.length) return;
    const h = document.createElement('div');
    h.className = 'rd-section';
    h.textContent = title;
    body.appendChild(h);
    arr.forEach((u) => {
      const row = document.createElement('div');
      row.className = 'rd-row';
      row.appendChild(avatarEl(u.uid, u.name, 'sm'));
      const nm = document.createElement('div');
      nm.className = 'm-name';
      nm.textContent = (u.uid === state.uid ? '我（' + u.name + '）' : u.name);
      row.appendChild(nm);
      body.appendChild(row);
    });
  };
  section(`已读（${readList.length}）`, readList);
  section(`未读（${unreadList.length}）`, unreadList);
  if (!readList.length && !unreadList.length) {
    body.innerHTML = '<div class="empty-hint">暂无成员信息</div>';
  }
  $('receiptModal').hidden = false;
}

// ---------- 成员抽屉 ----------
function renderMemberPanel() {
  const p = $('memberPanel');
  const c = state.convs[state.active];
  if (!c || p.hidden) return;
  const members = state.members[state.active] || [];
  p.innerHTML = '';
  const title = document.createElement('div');
  title.className = 'panel-title';
  title.innerHTML = `<span>群成员（${members.length}）</span>`;
  p.appendChild(title);
  members.forEach((u) => {
    const row = document.createElement('div');
    row.className = 'member';
    row.appendChild(avatarEl(u.uid, u.name, 'sm'));
    const nm = document.createElement('div');
    nm.className = 'm-name';
    nm.textContent = (u.uid === state.uid ? '我' : u.name);
    row.appendChild(nm);
    if (u.uid === state.uid) {
      const tag = document.createElement('span');
      tag.className = 'm-tag';
      tag.textContent = '当前';
      row.appendChild(tag);
    }
    p.appendChild(row);
  });
  const note = document.createElement('div');
  note.className = 'panel-note';
  note.innerHTML = `<b>飞书式已读回执</b><br>每条消息各自记录「谁读了」。` +
    `发送者在自己消息下方能看到「已读 X/Y」与读者头像，点击可展开详情。` +
    (c.is_big ? `<br><span class="big-badge">超大群降级：仅推进红点</span>` : '');
  p.appendChild(note);
}

// ---------- WS 业务回调 ----------
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
    refreshConvs(); // 非当前会话，仅刷新红点
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
  if (r.conv_id === state.active) renderMessages();
}

// ---------- 发送 ----------
function sendRead(convId, seq) {
  if (state.ws && state.ws.readyState === 1)
    state.ws.send(JSON.stringify({ type: 'read', conv_id: convId, seq }));
}
function send() {
  const txt = $('msgInput').value.trim();
  if (!txt || !state.ws) return;
  state.ws.send(JSON.stringify({ type: 'send', conv_id: state.active, content: txt, client_id: 'c' + Date.now() }));
  $('msgInput').value = '';
  autoGrow();
}
function autoGrow() {
  const t = $('msgInput');
  t.style.height = 'auto';
  t.style.height = Math.min(t.scrollHeight, 160) + 'px';
}

// ---------- 绑定 ----------
async function boot() {
  state.users = await getJSON('users');
  renderLoginUsers();

  $('railMe').onclick = () => {
    if (state.ws) state.ws.close();
    $('app').hidden = true;
    $('loginOverlay').hidden = false;
  };
  $('convSearch').addEventListener('input', renderConvList);
  $('memberBtn').onclick = () => {
    const p = $('memberPanel');
    p.hidden = !p.hidden;
    if (!p.hidden) renderMemberPanel();
  };
  $('searchBtn').onclick = () => { $('msgInput').focus(); };
  $('emojiBtn').onclick = () => {
    $('msgInput').value += '😊';
    autoGrow();
    $('msgInput').focus();
  };
  $('sendBtn').onclick = send;
  $('msgInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  $('msgInput').addEventListener('input', autoGrow);
  $('receiptClose').onclick = () => ($('receiptModal').hidden = true);
  $('receiptModal').addEventListener('click', (e) => {
    if (e.target === $('receiptModal')) $('receiptModal').hidden = true;
  });
  // 导航栏切换（演示仅「消息」可用）
  document.querySelectorAll('.rail-item').forEach((b) => {
    b.onclick = () => {
      if (b.dataset.nav !== 'msg') return;
      document.querySelectorAll('.rail-item').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
    };
  });
}
boot();
