// ============================================================================
// cyberspace-cs · 飞书式 IM 前端（原生 JS，无框架）
//
// 这一版把飞书桌面端「消息 + 通讯录」两页做实：
//   消息：会话 tab（全部/未读/@我）、置顶、免打扰、未读胶囊、引用回复、
//         @提及、表情回应、图片文件、撤回、转发、已读回执行、通知中心、全局搜索
//   通讯录：组织架构树 + 成员卡 + 名片 + 一键发起会话
// 其余模块保持诚实占位，不假装已实现。
// ============================================================================

const $ = (id) => document.getElementById(id);
const API = (p) => '/api/' + p;

const state = {
  token: '', uid: 0, me: null,
  users: {},            // uid -> user
  convs: {},            // conv_id -> conv
  convList: [],
  members: {},          // conv_id -> [user]
  msgs: {},             // conv_id -> [msg]
  receipts: {},         // msg_id -> {read_count,total,readers}
  summary: { total: 0, conv_unread: 0, at_me: 0, p2p: 0, group: 0 },
  active: null, tab: 'all',
  ws: null, wsReady: false, retry: 0,
  replyTo: null, atUIDs: [],
  typing: {}, notify: [], online: {},
  depts: [], activeDept: 0, infoOpen: false, viewing: 'msg',
  lastTypingSent: 0,
};
window.state = state;

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function avColor(uid) {
  const h = (Number(uid) * 47 + 205) % 360;
  return `hsl(${h} 42% 60%)`;
}
function initial(name) {
  if (!name) return '?';
  const s = String(name).trim();
  const m = s.match(/^[Uu]ser(\d+)$/);      // User01 -> 01，避免一屏全是 U
  if (m) return m[1].slice(-2);
  return /^[A-Za-z]/.test(s) ? s[0].toUpperCase() : s[0];
}
function avHTML(uid, size = 'md') {
  const u = state.users[uid] || { name: '?' };
  return `<div class="av ${size}" style="background:${avColor(uid)}">${esc(initial(u.name))}</div>`;
}
function nameOf(uid) {
  const u = state.users[uid];
  return u ? u.name : '用户' + uid;
}
function fmtTime(t) {
  const d = new Date(t);
  if (isNaN(d)) return '';
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  if (sameDay) return hm;
  const yest = new Date(now.getTime() - 864e5);
  if (d.toDateString() === yest.toDateString()) return '昨天 ' + hm;
  return `${d.getMonth() + 1}-${d.getDate()} ${hm}`;
}
function dayKey(t) {
  const d = new Date(t);
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}
function dayLabel(t) {
  const d = new Date(t);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return '今天';
  const yest = new Date(now.getTime() - 864e5);
  if (d.toDateString() === yest.toDateString()) return '昨天';
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`;
}
function toast(msg) {
  const el = $('toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.hidden = true), 2200);
}
function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (state.token) headers.Authorization = 'Bearer ' + state.token;
  const res = await fetch(API(path), { ...opts, headers });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = { error: text }; }
  if (!res.ok) throw new Error((data && data.error) || 'HTTP ' + res.status);
  return data;
}

// ---------------------------------------------------------------------------
// 登录
// ---------------------------------------------------------------------------
async function loadLoginUsers() {
  const users = await api('users');
  state.users = {};
  users.forEach((u) => (state.users[u.uid] = u));
  state.loginUsers = users;
  renderLoginUsers(users);
}
function renderLoginUsers(users) {
  const q = ($('loginFilter').value || '').trim();
  const list = users.filter((u) => !q || u.name.includes(q) || (u.dept || '').includes(q));
  $('loginUsers').innerHTML = list.map((u) => `
    <button class="user-card" data-uid="${u.uid}">
      ${avHTML(u.uid, 'md')}
      <div>
        <div class="uc-name">${esc(u.name)}</div>
        <div class="uc-sub">${esc(u.dept || '')}${u.dept_title ? ' · ' + esc(u.dept_title) : ''}</div>
      </div>
    </button>`).join('');
  $('loginUsers').querySelectorAll('.user-card').forEach((el) => {
    el.onclick = () => login(Number(el.dataset.uid));
  });
}
async function login(uid) {
  try {
    const r = await api('auth/login', { method: 'POST', body: JSON.stringify({ uid }) });
    state.token = r.token;
    state.uid = uid;
    state.me = r.user;
    state.users[uid] = r.user;
    try {
      localStorage.setItem('im_token', r.token);
      localStorage.setItem('im_uid', uid);
    } catch (e) {}
    await boot();
  } catch (e) { toast('登录失败：' + e.message); }
}

// ---------------------------------------------------------------------------
// 启动
// ---------------------------------------------------------------------------
async function boot() {
  $('login').hidden = true;
  $('app').hidden = false;
  $('meAvatar').innerHTML = avHTML(state.uid, 'sm');
  $('meAvatar').onclick = () => showProfile(state.uid);

  const [users, convs, summary] = await Promise.all([
    api('users'), api('conversations'), api('unread/summary'),
  ]);
  users.forEach((u) => (state.users[u.uid] = u));
  state.convList = convs || [];
  state.convs = {};
  state.convList.forEach((c) => (state.convs[c.conv_id] = c));
  state.summary = summary || state.summary;
  renderConvList();
  renderUnreadSummary();
  connectWS();
  loadNotifications();

  // 打开最近一个会话（飞书行为：默认落在上次会话）
  if (state.convList.length) openConv(state.convList[0].conv_id);
}

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  state.ws = ws;

  ws.onopen = () => {
    state.retry = 0;
    wsSend('login', { uid: state.uid, token: state.token });
  };
  ws.onmessage = (ev) => {
    let env;
    try { env = JSON.parse(ev.data); } catch (e) { return; }
    onWS(env.type, env.data || {});
  };
  ws.onclose = () => {
    state.wsReady = false;
    // 指数退避重连：1s, 2s, 4s ... 最多 15s
    const wait = Math.min(15000, 1000 * Math.pow(2, state.retry++));
    setTimeout(connectWS, wait);
  };
  ws.onerror = () => {};
}
function wsSend(type, data) {
  if (state.ws && state.ws.readyState === 1) {
    state.ws.send(JSON.stringify({ type, data: data || {} }));
  }
}

function onWS(type, d) {
  switch (type) {
    case 'welcome':
      state.wsReady = true;
      break;

    case 'ack':
      if (d.message) {
        addMessage(d.message, true);
        state.replyTo = null; state.atUIDs = [];
        hideReplyStrip();
      }
      break;

    case 'message': {
      const m = d;
      addMessage(m, false);
      const c = state.convs[m.conv_id];
      if (c) {
        if (m.conv_id !== state.active || state.viewing !== 'msg') {
          c.unread = (c.unread || 0) + 1;
          c.latest_seq = m.seq;
          c.last_content = m.content;
          c.last_sender_uid = m.sender_uid;
          renderConvList();
          refreshSummary();
        } else {
          // 正在看这个会话：立即上报已读（飞书同款行为）
          c.latest_seq = m.seq;
          sendRead(m.conv_id, m.seq);
          c.read_seq = m.seq;
          c.unread = 0;
          renderConvList();
        }
      }
      break;
    }

    case 'unread': {
      const c = state.convs[d.conv_id];
      if (c && (d.conv_id !== state.active || state.viewing !== 'msg')) {
        c.unread = d.unread;
        c.read_seq = d.read_seq;
        c.latest_seq = d.latest_seq;
        renderConvList();
      }
      break;
    }

    case 'receipt':
      state.receipts[d.msg_id] = {
        read_count: d.read_count, total: d.total, readers: d.readers || [],
      };
      updateReadLine(d.msg_id);
      break;

    case 'recall':
      markRecalled(d.msg_id);
      break;

    case 'reaction': {
      const list = state.msgs[d.conv_id] || [];
      const m = list.find((x) => x.msg_id === d.msg_id);
      if (m) { m.reactions = d.reactions || []; renderMessages(); }
      break;
    }

    case 'typing': {
      if (d.uid === state.uid) break;
      state.typing[d.conv_id] = { uid: d.uid, at: Date.now() };
      if (d.conv_id === state.active) showTyping();
      break;
    }

    case 'notify':
      loadNotifications(true);
      break;

    case 'error':
      if (d.msg) toast(d.msg);
      break;
  }
}

// ---------------------------------------------------------------------------
// 会话列表
// ---------------------------------------------------------------------------
function convTitle(c) {
  if (c.type === 2) return c.title || '群聊';
  const other = (state.members[c.conv_id] || []).find((u) => u.uid !== state.uid);
  if (other) return other.name;
  return nameOf(c.last_sender_uid || c.conv_id);
}
function convAvatar(c) {
  if (c.type === 2) {
    return `<div class="av md" style="background:linear-gradient(140deg,#5B8DEF,#3370FF)">${esc(initial(c.title || '群'))}</div>`;
  }
  const other = (state.members[c.conv_id] || []).find((u) => u.uid !== state.uid);
  return avHTML(other ? other.uid : c.conv_id, 'md');
}
function renderConvList() {
  const all = state.convList.slice().sort((a, b) => {
    if (!!b.pinned !== !!a.pinned) return b.pinned ? 1 : -1;
    return (b.latest_seq || 0) - (a.latest_seq || 0);
  });
  let list = all;
  if (state.tab === 'unread') list = all.filter((c) => c.unread > 0);
  if (state.tab === 'at') list = all.filter((c) => c.at_me);

  const pinned = list.filter((c) => c.pinned);
  const normal = list.filter((c) => !c.pinned);

  let html = '';
  if (pinned.length) html += `<div class="conv-group-label">置顶</div>` + pinned.map(convRow).join('');
  html += normal.map(convRow).join('');
  if (!list.length) {
    html = `<div class="sp-empty">${state.tab === 'unread' ? '没有未读会话' : state.tab === 'at' ? '没有人 @ 你' : '还没有会话'}</div>`;
  }
  $('convList').innerHTML = html;
  $('convList').querySelectorAll('.conv').forEach((el) => {
    const id = Number(el.dataset.id);
    el.onclick = () => openConv(id);
    el.oncontextmenu = (e) => { e.preventDefault(); convContextMenu(e, id); };
    const more = el.querySelector('.conv-more');
    if (more) more.onclick = (e) => { e.stopPropagation(); convContextMenu(e, id); };
  });
}
function convRow(c) {
  const active = c.conv_id === state.active ? ' active' : '';
  const unread = c.unread > 0
    ? `<span class="badge${c.muted ? ' mute' : ''}">${c.muted ? '' : (c.unread > 99 ? '99+' : c.unread)}</span>`
    : '';
  const at = c.at_me && c.unread > 0 ? `<span class="conv-at">@</span>` : '';
  const pin = c.pinned ? `<svg class="pin-flag" viewBox="0 0 24 24"><path d="M14 2l8 8-3 1-4 4 1 5-2 2-4-5-5-4 2-2 5 1 4-4z"/></svg>` : '';
  const muteIc = c.muted ? `<span style="color:#B4B9C1;font-size:11px">静音</span>` : '';
  const preview = (c.last_content || '').replace(/\n/g, ' ').slice(0, 40);
  const who = c.type === 2 && c.last_sender_uid ? nameOf(c.last_sender_uid) + '：' : '';
  return `
  <div class="conv${active}" data-id="${c.conv_id}">
    ${convAvatar(c)}
    <div class="conv-body">
      <div class="conv-row1">
        ${pin}
        <div class="conv-title">${esc(convTitle(c))}</div>
        <div class="conv-time">${c.last_at ? fmtTime(c.last_at) : ''}</div>
      </div>
      <div class="conv-row2">
        <div class="conv-msg">${who}${esc(preview)}</div>
        ${at}${muteIc}${unread}
      </div>
    </div>
    <button class="conv-more" title="更多">
      <svg viewBox="0 0 24 24" style="width:14px;height:14px"><path d="M12 5a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm0 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm0 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4z"/></svg>
    </button>
  </div>`;
}
function renderUnreadSummary() {
  const s = state.summary || {};
  const total = s.total || 0;
  const rb = $('railBadge');
  if (total > 0) { rb.hidden = false; rb.textContent = total > 99 ? '99+' : total; }
  else rb.hidden = true;

  const tu = $('tabUnread'), ta = $('tabAt');
  if (s.conv_unread > 0) { tu.hidden = false; tu.textContent = s.conv_unread; } else tu.hidden = true;
  if (s.at_me > 0) { ta.hidden = false; ta.textContent = s.at_me; } else ta.hidden = true;
}
async function refreshSummary() {
  try {
    state.summary = await api('unread/summary');
    renderUnreadSummary();
  } catch (e) {}
}

// 右键菜单：置顶 / 免打扰 / 标记未读
function convContextMenu(e, convID) {
  const c = state.convs[convID];
  if (!c) return;
  const menu = $('ctxMenu');
  menu.innerHTML = `
    <div class="ctx-item" data-act="pin">${c.pinned ? '取消置顶' : '置顶会话'}</div>
    <div class="ctx-item" data-act="mute">${c.muted ? '开启新消息提醒' : '消息免打扰'}</div>
    <div class="ctx-item" data-act="unread">标记为未读</div>
    <div class="ctx-item" data-act="open">打开会话</div>`;
  menu.hidden = false;
  const x = Math.min(e.clientX, innerWidth - 170);
  const y = Math.min(e.clientY, innerHeight - 160);
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  menu.querySelectorAll('.ctx-item').forEach((it) => {
    it.onclick = async () => {
      menu.hidden = true;
      const act = it.dataset.act;
      if (act === 'open') return openConv(convID);
      const body = { conv_id: convID };
      if (act === 'pin') body.pinned = !c.pinned;
      if (act === 'mute') body.muted = !c.muted;
      if (act === 'unread') body.marked_unread = true;
      try {
        await api('conversations/settings', { method: 'POST', body: JSON.stringify(body) });
        await reloadConvs();
      } catch (err) { toast(err.message); }
    };
  });
}
async function reloadConvs() {
  state.convList = await api('conversations');
  state.convs = {};
  state.convList.forEach((c) => (state.convs[c.conv_id] = c));
  renderConvList();
  refreshSummary();
}

// ---------------------------------------------------------------------------
// 打开会话
// ---------------------------------------------------------------------------
async function openConv(convID) {
  state.active = convID;
  state.replyTo = null;
  hideReplyStrip();
  $('chatEmpty').hidden = true;
  $('chatMain').hidden = false;
  renderConvList();

  const c = state.convs[convID];
  if (!c) return;

  if (!state.members[convID]) {
    try { state.members[convID] = await api('members?conv_id=' + convID); } catch (e) { state.members[convID] = []; }
  }
  const members = state.members[convID] || [];
  members.forEach((u) => (state.users[u.uid] = u));

  $('chatName').textContent = convTitle(c);
  const big = members.length > 200;
  $('chatMeta').textContent = c.type === 2
    ? `${members.length} 人${big ? ' · 超大群（已降级）' : ' · 单条已读回执'}`
    : '单聊 · 已读回执';
  $('composerTip').textContent = big
    ? '超大群：只推进红点，不维护精确单条回执'
    : 'Enter 发送 · Shift+Enter 换行 · 支持 @、引用、图片';
  renderHeadAvatars(members);

  let msgs = state.msgs[convID];
  if (!msgs) {
    try {
      msgs = await api(`messages?conv_id=${convID}&limit=40`);
      msgs = msgs.slice().sort((a, b) => a.seq - b.seq);
      state.msgs[convID] = msgs;
    } catch (e) { state.msgs[convID] = msgs = []; }
  }
  renderMessages();
  loadReceiptsFor(convID);

  $('msgInput').disabled = false;
  $('sendBtn').disabled = false;
  $('msgInput').focus({ preventScroll: true });

  // 打开即已读：推进水位线 + 乐观清零
  sendRead(convID, c.latest_seq);
  if (c.unread > 0 || c.marked_unread) {
    c.read_seq = c.latest_seq;
    c.unread = 0;
    c.marked_unread = false;
    renderConvList();
    refreshSummary();
    api('conversations/settings', {
      method: 'POST', body: JSON.stringify({ conv_id: convID, marked_unread: false }),
    }).catch(() => {});
  }
  renderInfoPanel();
}
function sendRead(convID, seq) {
  if (!seq) return;
  wsSend('read', { conv_id: convID, seq });
}
function renderHeadAvatars(members) {
  const others = members.filter((m) => m.uid !== state.uid);
  const list = others.slice(0, 3);
  let html = list.map((u) => avHTML(u.uid, 'sm')).join('');
  if (others.length > 3) {
    html += `<div class="av sm" style="background:#EEF1F6;color:#646A73;font-size:10px">+${others.length - 3}</div>`;
  }
  $('headAvatars').innerHTML = html;
}

// 只对自己的消息拉回执（最多最近 8 条），避免一次请求太多
async function loadReceiptsFor(convID) {
  const msgs = state.msgs[convID] || [];
  const mine = msgs.filter((m) => m.sender_uid === state.uid && m.seq).slice(-8);
  await Promise.all(mine.map(async (m) => {
    try {
      const rc = await api(`receipt?conv_id=${convID}&msg_id=${m.msg_id}&limit=5`);
      state.receipts[m.msg_id] = rc;
      updateReadLine(m.msg_id);
    } catch (e) {}
  }));
}

// ---------------------------------------------------------------------------
// 消息渲染
// ---------------------------------------------------------------------------
function addMessage(m, isMine) {
  const list = state.msgs[m.conv_id] || (state.msgs[m.conv_id] = []);
  if (list.some((x) => x.msg_id === m.msg_id)) return;
  list.push(m);
  list.sort((a, b) => a.seq - b.seq);
  if (m.conv_id === state.active) {
    const nearBottom = isNearBottom();
    renderMessages();
    if (nearBottom || isMine) scrollBottom();
  }
}
function isNearBottom() {
  const el = $('messages');
  return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
}
function scrollBottom() {
  const el = $('messages');
  el.scrollTop = el.scrollHeight;
  // 图片/字体撑高后再补一次，确保落在最新一条
  requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
}
function renderMessages() {
  const convID = state.active;
  const list = state.msgs[convID] || [];
  const box = $('messages');
  if (!list.length) {
    box.innerHTML = `<div class="sp-empty">还没有消息，说点什么吧</div>`;
    return;
  }
  let html = '';
  let lastDay = '';
  list.forEach((m) => {
    const dk = dayKey(m.created_at || Date.now());
    if (dk !== lastDay) {
      lastDay = dk;
      html += `<div class="date-sep">${dayLabel(m.created_at || Date.now())}</div>`;
    }
    html += msgHTML(m);
  });
  box.innerHTML = html;
  // 消息少时贴底显示（飞书观感），多时正常从顶部滚动
  box.classList.toggle('short', box.scrollHeight <= box.clientHeight + 4);
  bindMsgEvents();
  scrollBottom();
}
function msgHTML(m) {
  const mine = m.sender_uid === state.uid;
  if (m.recalled) {
    return `
    <div class="msg ${mine ? 'me' : ''}" data-id="${m.msg_id}">
      <div class="msg-av">${avHTML(m.sender_uid, 'md')}</div>
      <div class="msg-col">
        <div class="msg-head"><span class="msg-name">${esc(nameOf(m.sender_uid))}</span></div>
        <div class="bubble recalled">${mine ? '你' : esc(nameOf(m.sender_uid))} 撤回了一条消息</div>
      </div>
    </div>`;
  }

  let inner = '';
  if (m.quote) {
    inner += `<div class="quote"><b>${esc(nameOf(m.quote.sender_uid))}</b><span>${esc((m.quote.content || '').slice(0, 60))}</span></div>`;
  }
  if (m.files && m.files.length) {
    inner += m.files.map((f) => {
      const isImg = (f.mime || '').startsWith('image/');
      if (isImg) return `<img class="attach" src="${esc(f.url)}" alt="${esc(f.name)}">`;
      return `<div class="file-chip"><div class="file-ico">${(f.name.split('.').pop() || 'FILE').toUpperCase().slice(0, 4)}</div>
        <div><div class="file-name">${esc(f.name)}</div><div class="file-size">${fmtSize(f.size)}</div></div></div>`;
    }).join('');
  }
  if (m.content && !(m.files && m.files.length)) inner += `<span>${linkifyAt(m.content, m.at_uids)}</span>`;

  const reactions = (m.reactions && m.reactions.length) ? `<div class="reactions">${m.reactions.map((r) => `
    <button class="reaction${r.mine ? ' mine' : ''}" data-emoji="${esc(r.emoji)}">${esc(r.emoji)}<span>${r.count}</span></button>`).join('')}</div>` : '';

  const readLine = mine ? `<div class="read-line" data-read="${m.msg_id}"></div>` : '';

  return `
  <div class="msg ${mine ? 'me' : ''}" data-id="${m.msg_id}" data-seq="${m.seq}">
    <div class="msg-av" data-uid="${m.sender_uid}">${avHTML(m.sender_uid, 'md')}</div>
    <div class="msg-col">
      <div class="msg-head">
        <span class="msg-name">${esc(nameOf(m.sender_uid))}</span>
        <span class="msg-time">${fmtTime(m.created_at)}</span>
      </div>
      <div class="bubble">${inner}</div>
      ${reactions}
      ${readLine}
    </div>
    <div class="msg-tools">
      <button class="mtool" data-act="reply" title="回复">
        <svg viewBox="0 0 24 24"><path d="M9 4L2 11l7 7v-5c6 0 9 2 11 6 0-8-4-13-11-13V4z"/></svg>
      </button>
      <button class="mtool" data-act="react" title="表情回应">☺</button>
      <button class="mtool" data-act="copy" title="复制">⧉</button>
      ${mine ? `<button class="mtool" data-act="recall" title="撤回">↺</button>` : ''}
      <button class="mtool" data-act="forward" title="转发">
        <svg viewBox="0 0 24 24"><path d="M14 4l8 7-8 7v-4c-6 0-9 2-11 5 0-8 4-13 11-13V4z"/></svg>
      </button>
    </div>
  </div>`;
}
function linkifyAt(text, atUids) {
  let s = esc(text);
  if (atUids && atUids.length) {
    atUids.forEach((uid) => {
      const nm = esc(nameOf(uid));
      s = s.split('@' + nm).join(`<span class="at">@${nm}</span>`);
    });
  }
  s = s.replace(/@所有人/g, '<span class="at">@所有人</span>');
  return s;
}
function fmtSize(n) {
  if (!n) return '';
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1048576).toFixed(1) + ' MB';
}

function bindMsgEvents() {
  document.querySelectorAll('.msg').forEach((el) => {
    const mid = Number(el.dataset.id);
    const bubble = el.querySelector('.bubble');
    if (bubble && bubble.classList.contains('recalled')) return;

    el.querySelectorAll('.mtool').forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const act = btn.dataset.act;
        if (act === 'reply') startReply(mid);
        if (act === 'react') openEmoji(e, (emoji) => doReaction(mid, emoji));
        if (act === 'copy') {
          const m = findMsg(mid);
          navigator.clipboard.writeText(m ? m.content : '').then(() => toast('已复制'));
        }
        if (act === 'recall') doRecall(mid);
        if (act === 'forward') openForward(mid);
      };
    });
    const av = el.querySelector('.msg-av');
    if (av) av.onclick = () => showProfile(Number(av.dataset.uid));

    el.querySelectorAll('.reaction').forEach((r) => {
      r.onclick = () => doReaction(mid, r.dataset.emoji);
    });
    const rl = el.querySelector('.read-line');
    if (rl) rl.onclick = () => openReceipt(mid);
  });
  Object.keys(state.receipts).forEach((id) => updateReadLine(Number(id)));
}
function findMsg(mid) {
  const list = state.msgs[state.active] || [];
  return list.find((m) => m.msg_id === mid);
}
function updateReadLine(mid) {
  const el = document.querySelector(`.read-line[data-read="${mid}"]`);
  if (!el) return;
  const rc = state.receipts[mid];
  if (!rc || !rc.total) {
    el.className = 'read-line sent';
    el.innerHTML = '已送达';
    return;
  }
  const readers = (rc.readers || []).slice(0, 5);
  const avs = readers.map((uid) => avHTML(uid, 'xs')).join('');
  if (rc.read_count > 0) {
    el.className = 'read-line';
    el.innerHTML = `<span class="rv">${avs}</span>已读 ${rc.read_count}/${rc.total}`;
  } else {
    el.className = 'read-line sent';
    el.innerHTML = `未读 · 已送达`;
  }
}
function markRecalled(mid) {
  const list = state.msgs[state.active] || [];
  const m = list.find((x) => x.msg_id === mid);
  if (m) { m.recalled = true; m.content = ''; renderMessages(); }
}

// ---------------------------------------------------------------------------
// 消息动作：回复 / 表情 / 撤回 / 转发
// ---------------------------------------------------------------------------
function startReply(mid) {
  const m = findMsg(mid);
  if (!m) return;
  state.replyTo = mid;
  $('replyStrip').hidden = false;
  $('replyText').textContent = `${nameOf(m.sender_uid)}：${(m.content || '[非文本消息]').slice(0, 50)}`;
  $('msgInput').focus();
}
function hideReplyStrip() {
  $('replyStrip').hidden = true;
}
function doReaction(mid, emoji) {
  const m = findMsg(mid);
  if (!m) return;
  wsSend('reaction', { conv_id: m.conv_id, msg_id: mid, emoji });
}
function doRecall(mid) {
  const m = findMsg(mid);
  if (!m) return;
  if (!confirm('撤回这条消息？')) return;
  wsSend('recall', { conv_id: m.conv_id, msg_id: mid });
}
async function openForward(mid) {
  const list = state.convList.filter((c) => c.conv_id !== state.active);
  openModal('转发到', `
    <div class="pick-list" id="fwdList">
      ${list.map((c) => `<label class="pick-row"><input type="checkbox" value="${c.conv_id}">
        <span class="pick-name">${esc(convTitle(c))}</span></label>`).join('') || '<div class="sp-empty">没有其他会话</div>'}
    </div>
    <button class="btn" id="fwdGo">转发</button>`);
  const go = $('fwdGo');
  if (!go) return;
  go.onclick = async () => {
    const ids = [...document.querySelectorAll('#fwdList input:checked')].map((i) => Number(i.value));
    if (!ids.length) return toast('请选择会话');
    try {
      await api('messages/forward', { method: 'POST', body: JSON.stringify({ msg_id: mid, to_conv_ids: ids }) });
      closeModal();
      toast('已转发');
      reloadConvs();
    } catch (e) { toast(e.message); }
  };
}

// 表情面板
const EMOJIS = ['😀','😄','😊','😉','😍','🤔','😅','😭','😡','👍','👎','👏','🙏','💪','🎉','🔥','❤️','💯','✅','❌','🚀','☕','🐛','📌','👀','🤝','😴','🤯','🥳','🌟','⚡','💡'];
function openEmoji(e, cb) {
  const p = $('emojiPanel');
  p.className = 'emoji-panel';
  p.style.gridTemplateColumns = 'repeat(8,1fr)';
  p.style.width = '280px';
  p.innerHTML = EMOJIS.map((x) => `<button data-e="${x}">${x}</button>`).join('');
  p.hidden = false;
  p.style.left = Math.min(e.clientX, innerWidth - 292) + 'px';
  p.style.top = Math.max(12, e.clientY - 160) + 'px';
  p.querySelectorAll('button').forEach((b) => {
    b.onclick = () => { p.hidden = true; cb(b.dataset.e); };
  });
}

// ---------------------------------------------------------------------------
// 发送
// ---------------------------------------------------------------------------
function sendMessage() {
  const input = $('msgInput');
  const text = input.value.trim();
  if (!text || !state.active) return;
  const payload = { conv_id: state.active, content: text, type: 1, client_id: String(Date.now()) };
  if (state.replyTo) payload.reply_to = state.replyTo;
  if (state.atUIDs.length) payload.at_uids = state.atUIDs;
  wsSend('send', payload);
  input.value = '';
  input.style.height = '38px';
  state.atUIDs = [];
}
async function sendFile(file) {
  if (!file || !state.active) return;
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch(API('upload'), {
    method: 'POST', headers: { Authorization: 'Bearer ' + state.token }, body: fd,
  });
  const data = await res.json();
  if (!res.ok) return toast(data.error || '上传失败');
  const isImg = (data.mime || '').startsWith('image/');
  wsSend('send', {
    conv_id: state.active,
    content: data.name,
    type: isImg ? 2 : 3,
    client_id: String(Date.now()),
    files: [data],
  });
}

// ---------------------------------------------------------------------------
// 已读回执弹窗
// ---------------------------------------------------------------------------
async function openReceipt(mid) {
  const convID = state.active;
  const members = state.members[convID] || [];
  let rc = state.receipts[mid];
  try {
    rc = await api(`receipt?conv_id=${convID}&msg_id=${mid}&limit=500`);
    state.receipts[mid] = rc;
  } catch (e) {}
  if (!rc) return toast('暂无回执数据');

  const readers = new Set(rc.readers || []);
  const sender = (findMsg(mid) || {}).sender_uid;
  const readList = members.filter((u) => readers.has(u.uid));
  const unreadList = members.filter((u) => u.uid !== sender && !readers.has(u.uid));

  const rows = (arr) => arr.map((u) => `
    <div class="rd-row">${avHTML(u.uid, 'sm')}
      <div class="rd-name">${esc(u.name)}${u.uid === state.uid ? '（我）' : ''}</div>
    </div>`).join('');

  openModal(`已读详情（${rc.read_count}/${rc.total}）`, `
    <div class="rd-grid">
      <div class="rd-col">
        <div class="rd-h">已读 <span class="n">${readList.length}</span></div>
        <div class="rd-list">${rows(readList) || '<div class="sp-empty">还没有人读</div>'}</div>
      </div>
      <div class="rd-col">
        <div class="rd-h">未读 <span class="n">${unreadList.length}</span></div>
        <div class="rd-list">${rows(unreadList)}</div>
      </div>
    </div>`, 'wide');
}

// ---------------------------------------------------------------------------
// 名片
// ---------------------------------------------------------------------------
function showProfile(uid) {
  const u = state.users[uid];
  if (!u) return;
  const mine = uid === state.uid;
  openModal('', `
    <div class="profile-top">
      ${avHTML(uid, 'xl')}
      <div>
        <div class="profile-name">${esc(u.name)}</div>
        <div class="profile-sub">${esc(u.dept || '未分配部门')}${u.dept_title ? ' · ' + esc(u.dept_title) : ''}</div>
      </div>
    </div>
    <div class="profile-fields">
      <div class="pf"><span>邮箱</span><b>${esc(u.email || '—')}</b></div>
      <div class="pf"><span>手机</span><b>${esc(u.phone || '—')}</b></div>
      <div class="pf"><span>UID</span><b>${uid}</b></div>
    </div>
    <div class="profile-actions">
      ${mine ? `<button class="btn ghost" id="pfLogout">退出登录</button>`
             : `<button class="btn" id="pfMsg">发消息</button><button class="btn ghost" id="pfClose">关闭</button>`}
    </div>`);
  const pm = $('pfMsg');
  if (pm) pm.onclick = async () => {
    const r = await api('conversations', { method: 'POST', body: JSON.stringify({ type: 1, members: [uid] }) });
    closeModal();
    await reloadConvs();
    openConv(r.conv_id);
  };
  const pl = $('pfLogout');
  if (pl) pl.onclick = () => { try { localStorage.clear(); } catch (e) {} location.reload(); };
  const pc = $('pfClose');
  if (pc) pc.onclick = closeModal;
}

// ---------------------------------------------------------------------------
// 侧栏信息面板
// ---------------------------------------------------------------------------
function renderInfoPanel() {
  const convID = state.active;
  const c = state.convs[convID];
  const members = state.members[convID] || [];
  const panel = $('infoPanel');
  if (!c) { panel.hidden = true; return; }
  // 默认收起，点右上「信息」才展开（避免挤压消息区）
  panel.hidden = !state.infoOpen;
  const list = members.slice(0, 30).map((u) => `
    <div class="ip-member" data-uid="${u.uid}">
      ${avHTML(u.uid, 'sm')}
      <div><div class="ip-name">${esc(u.name)}${u.uid === state.uid ? '（我）' : ''}</div>
        <div class="ip-dept">${esc(u.dept || '')}${u.dept_title ? ' · ' + esc(u.dept_title) : ''}</div></div>
    </div>`).join('');
  panel.innerHTML = `
    <div class="ip-title">会话信息</div>
    <div class="ip-row"><span>类型</span><b>${c.type === 2 ? '群聊' : '单聊'}</b></div>
    <div class="ip-row"><span>成员</span><b>${members.length} 人</b></div>
    <div class="ip-row"><span>最新序号</span><b>${c.latest_seq || 0}</b></div>
    <div class="ip-row"><span>未读</span><b>${c.unread || 0}</b></div>
    <div class="ip-sub">成员 ${members.length}</div>
    ${list}
    <div class="ip-actions">
      <button class="ip-btn" id="ipAdd">加人</button>
      <button class="ip-btn danger" id="ipLeave">${c.type === 2 ? '退出群聊' : '关闭会话'}</button>
    </div>`;
  panel.querySelectorAll('.ip-member').forEach((el) => {
    el.onclick = () => showProfile(Number(el.dataset.uid));
  });
  $('ipAdd').onclick = () => openAddMember(convID);
  $('ipLeave').onclick = async () => {
    if (!confirm(c.type === 2 ? '确认退出该群？' : '确认删除该会话？')) return;
    try {
      await api('conversations/members', { method: 'POST', body: JSON.stringify({ conv_id: convID, op: 'leave' }) });
      state.active = null;
      $('chatMain').hidden = true;
      $('chatEmpty').hidden = false;
      $('infoPanel').hidden = true;
      await reloadConvs();
      toast('已退出');
    } catch (e) { toast(e.message); }
  };
}

async function openAddMember(convID) {
  const members = state.members[convID] || [];
  const inIds = new Set(members.map((m) => m.uid));
  const users = await api('users');
  const cand = users.filter((u) => !inIds.has(u.uid)).slice(0, 80);
  openModal('添加成员', `
    <div class="pick-list" id="addList">
      ${cand.map((u) => `<label class="pick-row"><input type="checkbox" value="${u.uid}">
        <span class="pick-name">${esc(u.name)}<span style="color:#8F959E;font-size:11px"> · ${esc(u.dept || '')}</span></span></label>`).join('')}
    </div>
    <button class="btn" id="addGo">添加</button>`);
  $('addGo').onclick = async () => {
    const ids = [...document.querySelectorAll('#addList input:checked')].map((i) => Number(i.value));
    if (!ids.length) return toast('请选择成员');
    try {
      await api('conversations/members', { method: 'POST', body: JSON.stringify({ conv_id: convID, op: 'add', uids: ids }) });
      state.members[convID] = null;
      closeModal();
      toast('已添加');
      openConv(convID);
    } catch (e) { toast(e.message); }
  };
}

// ---------------------------------------------------------------------------
// 新建会话
// ---------------------------------------------------------------------------
async function openNewConv() {
  const users = await api('users');
  const cand = users.filter((u) => u.uid !== state.uid).slice(0, 100);
  openModal('发起会话', `
    <div class="seg" id="convType" style="margin-bottom:12px">
      <button class="on" data-t="2">群聊</button><button data-t="1">单聊</button>
    </div>
    <div class="field" id="titleField"><label>群名称（群聊必填）</label><input id="convTitle" placeholder="例如：Q4 发布协作群"></div>
    <div style="font-size:12px;color:#646A73;margin-bottom:6px">选择成员</div>
    <div class="pick-list" id="newList">
      ${cand.map((u) => `<label class="pick-row"><input type="checkbox" value="${u.uid}">
        <span class="pick-name">${esc(u.name)}<span style="color:#8F959E;font-size:11px"> · ${esc(u.dept || '')}</span></span></label>`).join('')}
    </div>
    <button class="btn" id="newGo">创建</button>`);

  let type = 2;
  document.querySelectorAll('#convType button').forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll('#convType button').forEach((x) => x.classList.remove('on'));
      b.classList.add('on');
      type = Number(b.dataset.t);
      $('titleField').style.display = type === 2 ? '' : 'none';
      document.querySelectorAll('#newList input').forEach((i) => {
        i.type = type === 2 ? 'checkbox' : 'radio';
        i.checked = false;
      });
    };
  });
  $('newGo').onclick = async () => {
    const ids = [...document.querySelectorAll('#newList input:checked')].map((i) => Number(i.value));
    if (!ids.length) return toast('请选择成员');
    const title = ($('convTitle') || {}).value || '';
    try {
      const r = await api('conversations', { method: 'POST', body: JSON.stringify({ type, title: title.trim(), members: ids }) });
      closeModal();
      await reloadConvs();
      openConv(r.conv_id);
      toast('会话已创建');
    } catch (e) { toast(e.message); }
  };
}

// ---------------------------------------------------------------------------
// 全局搜索
// ---------------------------------------------------------------------------
const doSearch = debounce(async (q) => {
  const panel = $('searchPanel');
  if (!q) { panel.hidden = true; return; }
  let hits = [];
  try { hits = (await api('search?q=' + encodeURIComponent(q))).hits || []; } catch (e) {}
  const groups = { message: [], user: [], conv: [] };
  hits.forEach((h) => (groups[h.kind] || groups.message).push(h));
  const title = { message: '消息', user: '联系人', conv: '群组' };
  let html = '';
  ['message', 'user', 'conv'].forEach((k) => {
    if (!groups[k].length) return;
    html += `<div class="sp-sec">${title[k]}</div>`;
    html += groups[k].map((h) => {
      const snip = hl(h.snippet || '', q);
      const icon = k === 'user' ? avHTML(h.uid, 'sm')
        : `<div class="av sm" style="background:#EAF0FF;color:#3370FF;padding:6px">${k === 'conv'
            ? '<svg viewBox="0 0 24 24"><path d="M8 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zm8 0a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2 20a6 6 0 0 1 12 0v1H2v-1z"/></svg>'
            : '<svg viewBox="0 0 24 24"><path d="M4 4h16a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H9l-5 4V5a1 1 0 0 1 1-1z"/></svg>'}</div>`;
      return `<div class="sp-hit" data-kind="${k}" data-id="${h.id}" data-conv="${h.conv_id || 0}" data-seq="${h.seq || 0}">
        ${icon}<div style="min-width:0">
          <div class="sp-hit-t">${esc(h.title)}</div>
          <div class="sp-hit-s">${snip}</div>
        </div></div>`;
    }).join('');
  });
  $('spBody').innerHTML = html || '<div class="sp-empty">没有找到相关内容</div>';
  panel.hidden = false;
  $('spBody').querySelectorAll('.sp-hit').forEach((el) => {
    el.onclick = () => {
      panel.hidden = true;
      const kind = el.dataset.kind;
      if (kind === 'user') return showProfile(Number(el.dataset.id));
      const convID = Number(el.dataset.conv) || Number(el.dataset.id);
      openConv(convID).then(() => {
        const seq = Number(el.dataset.seq);
        if (seq) {
          const node = document.querySelector(`.msg[data-seq="${seq}"]`);
          if (node) {
            node.scrollIntoView({ block: 'center' });
            const b = node.querySelector('.bubble');
            if (b) {
              b.style.background = '#FFF3C4';
              setTimeout(() => (b.style.background = ''), 1600);
            }
          }
        }
      });
    };
  });
}, 260);

function hl(text, q) {
  const s = esc(text);
  if (!q) return s;
  return s.split(esc(q)).join(`<mark>${esc(q)}</mark>`);
}

// ---------------------------------------------------------------------------
// 通知
// ---------------------------------------------------------------------------
async function loadNotifications(quiet) {
  try {
    state.notify = await api('notifications');
    const unread = state.notify.filter((n) => !n.read).length;
    $('notifyDot').hidden = unread === 0;
    renderNotifications();
  } catch (e) {}
}
function renderNotifications() {
  const list = state.notify || [];
  $('notifyList').innerHTML = list.length ? list.map((n) => `
    <div class="nt">
      <div class="av sm" style="background:#FFF3F2;color:#F54A45">@</div>
      <div style="min-width:0">
        <div class="nt-t">${esc(n.title)}</div>
        <div class="nt-b">${esc(n.body || '')}</div>
        <div class="nt-time">${fmtTime(n.created_at)}</div>
      </div>
    </div>`).join('') : '<div class="sp-empty">暂无通知</div>';
}

// ---------------------------------------------------------------------------
// 通讯录
// ---------------------------------------------------------------------------
async function loadOrg() {
  const r = await api('org/tree');
  state.depts = r.depts || [];
  renderOrgTree();
  if (state.depts.length) selectDept(state.depts[0].dept_id);
}
function renderOrgTree() {
  $('orgTree').innerHTML = state.depts.map((d) => `
    <div class="org-node${d.dept_id === state.activeDept ? ' active' : ''}" data-id="${d.dept_id}">
      <svg viewBox="0 0 24 24" style="width:15px;height:15px;color:#8F959E"><path d="M3 5h7l2 2h9v12H3z"/></svg>
      <span>${esc(d.name)}</span><i class="org-num">${d.count}</i>
    </div>`).join('');
  $('orgTree').querySelectorAll('.org-node').forEach((el) => {
    el.onclick = () => selectDept(Number(el.dataset.id));
  });
}
function selectDept(id) {
  state.activeDept = id;
  renderOrgTree();
  const d = state.depts.find((x) => x.dept_id === id);
  if (!d) return;
  $('deptName').textContent = d.name;
  $('deptCount').textContent = `${d.count} 人`;
  $('orgMembers').innerHTML = (d.members || []).map((u) => `
    <div class="oc" data-uid="${u.uid}">
      ${avHTML(u.uid, 'md')}
      <div style="min-width:0">
        <div class="oc-name">${esc(u.name)}${u.uid === state.uid ? '<span class="online-dot"></span>' : ''}</div>
        <div class="oc-title">${esc(u.dept_title || '')}</div>
        <div class="oc-mail">${esc(u.email || '')}</div>
      </div>
    </div>`).join('');
  $('orgMembers').querySelectorAll('.oc').forEach((el) => {
    el.onclick = () => showProfile(Number(el.dataset.uid));
  });
}

// ---------------------------------------------------------------------------
// 视图切换
// ---------------------------------------------------------------------------
const PLACEHOLDER = {
  docs: ['云文档', '在线文档、表格、思维笔记的协作空间。真实产品里这里是块编辑器 + 实时协同光标 + 评论侧栏。', '<path d="M6 2h8l4 4v16H6V2zm8 1.5V7h3.5L14 3.5z"/>'],
  calendar: ['日历', '共享团队日历、会议室预订、一键建会议群。后端需要日程 CRUD + 空闲时间检索 + 会议室资源锁。', '<path d="M5 4h14a1 1 0 0 1 1 1v15H4V5a1 1 0 0 1 1-1zm0 5h14M8 3v3m8-3v3"/>'],
  meeting: ['视频会议', '四宫格视频 + 智能纪要。需要 SFU 媒体服务器与 WebRTC 信令，超出本期范围。', '<path d="M3 6h13v12H3V6zm15 3l4-2v10l-4-2V9z"/>'],
  settings: ['设置', '通知偏好、快捷键、账号安全。当前项目只保留身份切换入口。', '<path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"/>'],
};
function switchView(view) {
  state.viewing = view;
  document.querySelectorAll('.rail-item').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  document.querySelectorAll('.view').forEach((v) => (v.hidden = true));
  if (view === 'msg') {
    $('viewMsg').hidden = false;
    // 切回消息页：当前会话的未读立即清掉（人已经在看了）
    const c = state.convs[state.active];
    if (c && c.unread > 0) {
      sendRead(c.conv_id, c.latest_seq);
      c.read_seq = c.latest_seq;
      c.unread = 0;
      renderConvList();
      refreshSummary();
    }
  } else if (view === 'contacts') {
    $('viewContacts').hidden = false;
    if (!state.depts.length) loadOrg();
  } else {
    const p = PLACEHOLDER[view] || ['模块', '', ''];
    $('phTitle').textContent = p[0];
    $('phDesc').textContent = p[1];
    $('phIcon').innerHTML = `<svg viewBox="0 0 24 24"><path d="${p[2]}"/></svg>`;
    $('viewPlaceholder').hidden = false;
  }
}

// ---------------------------------------------------------------------------
// 弹窗
// ---------------------------------------------------------------------------
function openModal(title, body, cls) {
  $('modalTitle').textContent = title || '';
  $('modalTitle').style.display = title ? '' : 'none';
  $('modalBody').innerHTML = body;
  $('modalCard').className = 'modal-card' + (cls ? ' ' + cls : '');
  $('modal').hidden = false;
}
function closeModal() { $('modal').hidden = true; }

// ---------------------------------------------------------------------------
// 事件绑定
// ---------------------------------------------------------------------------
function bindGlobal() {
  $('loginFilter').oninput = () => renderLoginUsers(state.loginUsers || []);

  document.querySelectorAll('.rail-item').forEach((b) => {
    b.onclick = () => switchView(b.dataset.view);
  });

  document.querySelectorAll('.conv-tab').forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll('.conv-tab').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.tab = b.dataset.tab;
      renderConvList();
    };
  });

  const input = $('msgInput');
  input.oninput = () => {
    input.style.height = '38px';
    input.style.height = Math.min(150, input.scrollHeight) + 'px';
    if (Date.now() - state.lastTypingSent > 3000 && state.active) {
      state.lastTypingSent = Date.now();
      wsSend('typing', { conv_id: state.active });
    }
  };
  input.onkeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  };
  $('sendBtn').onclick = sendMessage;
  $('replyClose').onclick = () => { state.replyTo = null; hideReplyStrip(); };

  $('emojiBtn').onclick = (e) => {
    openEmoji(e, (emoji) => {
      const i = $('msgInput');
      i.value += emoji;
      i.focus();
      i.oninput();
    });
  };

  // @ 提及
  $('atBtn').onclick = (e) => {
    const members = (state.members[state.active] || []).filter((u) => u.uid !== state.uid);
    const p = $('emojiPanel');
    p.className = 'emoji-panel';
    p.style.gridTemplateColumns = '1fr';
    p.style.width = '180px';
    p.innerHTML = `<button data-uid="0" style="font-size:13px;text-align:left;padding:6px 8px">@所有人</button>` +
      members.map((u) => `<button data-uid="${u.uid}" style="font-size:13px;text-align:left;padding:6px 8px">${esc(u.name)}</button>`).join('');
    p.hidden = false;
    p.style.left = Math.min(e.clientX, innerWidth - 200) + 'px';
    p.style.top = Math.max(12, e.clientY - Math.min(340, 46 + members.length * 32)) + 'px';
    p.querySelectorAll('button').forEach((b) => {
      b.onclick = () => {
        const uid = Number(b.dataset.uid);
        const nm = uid === 0 ? '所有人' : nameOf(uid);
        const i = $('msgInput');
        i.value += '@' + nm + ' ';
        if (uid) state.atUIDs.push(uid);
        p.hidden = true;
        p.style.gridTemplateColumns = 'repeat(8,1fr)';
        p.style.width = '280px';
        i.focus();
        i.oninput();
      };
    });
  };

  $('uploadBtn').onclick = () => {
    const f = document.createElement('input');
    f.type = 'file';
    f.onchange = () => f.files[0] && sendFile(f.files[0]);
    f.click();
  };
  input.addEventListener('paste', (e) => {
    const item = [...((e.clipboardData && e.clipboardData.items) || [])].find((i) => i.type.startsWith('image/'));
    if (item) { e.preventDefault(); sendFile(item.getAsFile()); }
  });

  $('globalSearch').oninput = (e) => doSearch(e.target.value.trim());
  $('globalSearch').onfocus = (e) => { if (e.target.value.trim()) doSearch(e.target.value.trim()); };
  $('newConvBtn').onclick = openNewConv;
  $('convMoreBtn').onclick = (e) => {
    const menu = $('ctxMenu');
    menu.innerHTML = `<div class="ctx-item" data-act="new">发起会话</div>
      <div class="ctx-item" data-act="readall">全部标记已读</div>`;
    menu.hidden = false;
    menu.style.left = Math.min(e.clientX, innerWidth - 170) + 'px';
    menu.style.top = e.clientY + 8 + 'px';
    menu.querySelectorAll('.ctx-item').forEach((it) => {
      it.onclick = async () => {
        menu.hidden = true;
        if (it.dataset.act === 'new') return openNewConv();
        for (const c of state.convList) {
          if (c.unread > 0) sendRead(c.conv_id, c.latest_seq);
        }
        state.convList.forEach((c) => { c.unread = 0; c.read_seq = c.latest_seq; });
        renderConvList();
        refreshSummary();
        toast('已全部标记已读');
      };
    });
  };

  $('notifyBtn').onclick = () => {
    const p = $('notifyPanel');
    p.hidden = !p.hidden;
    if (!p.hidden) renderNotifications();
  };
  $('notifyReadAll').onclick = async () => {
    await api('notifications/read', { method: 'POST', body: '{}' });
    loadNotifications();
    toast('已全部已读');
  };

  $('infoBtn').onclick = () => {
    const p = $('infoPanel');
    state.infoOpen = !state.infoOpen;
    p.hidden = !state.infoOpen;
  };
  $('searchConvBtn').onclick = () => {
    $('globalSearch').focus();
    toast('输入关键词搜索全部消息');
  };

  $('modalClose').onclick = closeModal;
  $('modal').onclick = (e) => { if (e.target.id === 'modal') closeModal(); };

  document.addEventListener('click', (e) => {
    const ep = $('emojiPanel');
    if (!ep.hidden && !ep.contains(e.target) && !e.target.closest('#emojiBtn') && !e.target.closest('#atBtn')) {
      ep.hidden = true;
      ep.style.gridTemplateColumns = 'repeat(8,1fr)';
      ep.style.width = '280px';
    }
    const cm = $('ctxMenu');
    if (!cm.hidden && !cm.contains(e.target)) cm.hidden = true;
    const sp = $('searchPanel');
    if (!sp.hidden && !sp.contains(e.target) && !e.target.closest('.tb-search-wrap')) sp.hidden = true;
    const np = $('notifyPanel');
    if (!np.hidden && !np.contains(e.target) && !e.target.closest('#notifyBtn')) np.hidden = true;
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      $('searchPanel').hidden = true;
      $('emojiPanel').hidden = true;
      $('ctxMenu').hidden = true;
      $('notifyPanel').hidden = true;
      if (!$('modal').hidden) closeModal();
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      $('globalSearch').focus();
    }
  });
  window.addEventListener('resize', () => { $('ctxMenu').hidden = true; });

  setInterval(() => {
    if (!state.active) return;
    const t = state.typing[state.active];
    if (t && Date.now() - t.at > 4000) {
      delete state.typing[state.active];
      $('typingBar').hidden = true;
    }
  }, 1000);
}
function showTyping() {
  const t = state.typing[state.active];
  if (!t) return;
  $('typingBar').hidden = false;
  $('typingBar').textContent = `${nameOf(t.uid)} 正在输入…`;
}

// ---------------------------------------------------------------------------
// 启动
// ---------------------------------------------------------------------------
(async function init() {
  bindGlobal();
  try {
    await loadLoginUsers();
  } catch (e) {
    toast('加载用户失败：' + e.message);
  }
  // 自动恢复登录态（刷新免重登）
  let savedTok = '', savedUID = 0;
  try {
    savedTok = localStorage.getItem('im_token') || '';
    savedUID = Number(localStorage.getItem('im_uid') || 0);
  } catch (e) {}
  if (savedTok && savedUID) {
    try {
      const me = await api('auth/me?token=' + savedTok);
      state.token = savedTok;
      state.uid = savedUID;
      state.me = me;
      state.users[savedUID] = me;
      await boot();
    } catch (e) {
      try { localStorage.clear(); } catch (x) {}
    }
  }
})();
