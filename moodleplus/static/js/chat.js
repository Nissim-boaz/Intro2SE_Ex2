// Course chat: polling every 2.5s, bubbles, reply-with-quote, reactions, polls,
// delete-own-message and read receipts (WhatsApp-style ticks).
//
// Desktop: hovering a message shows two small buttons beside it: ☺ opens the emoji row,
//          ⌄ opens the menu (reply / message info / delete). Nothing opens by hover alone.
// Phone:   long-press opens both together.
(function () {
  const root = document.getElementById("chat-root");
  if (!root) return;
  const listUrl = root.dataset.listUrl;
  const sendUrl = root.dataset.sendUrl;
  const readUrl = root.dataset.readUrl;
  const pollUrl = root.dataset.pollUrl;
  const POLL_MS = 2500;
  // inside the course page (see chat_sheet.js): load once, then poll and mark as read only while it is open
  const embedded = document.body.classList.contains("chat-embedded") && window.parent !== window;
  let active = !embedded;

  const scroller = document.getElementById("chat-scroll");
  const list = document.getElementById("chat-list");
  const empty = document.getElementById("chat-empty");
  const pop = document.getElementById("msg-pop");
  const bar = document.getElementById("reaction-bar");
  const menu = document.getElementById("msg-menu");
  const confirmBox = document.getElementById("msg-confirm");
  const input = document.getElementById("chat-input");
  const status = document.getElementById("chat-status");
  const esc = Model.escape;

  const messages = new Map(); // id -> message
  let receipts = { audience: 0, read: {} };
  let since = 0;
  let replyTo = null;
  let popFor = null;
  let timer = null;
  let lastMarked = 0;
  let chatVisible = false;

  // ---------- rendering ----------
  const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });

  function fmtWhen(ts) {
    const d = new Date(ts * 1000);
    const today = new Date();
    const day = d.toDateString() === today.toDateString()
      ? "היום"
      : d.toLocaleDateString("he-IL", { day: "numeric", month: "numeric" });
    return day + " " + fmtTime(ts);
  }

  // one tick = sent, two grey = someone read, two blue = everyone in the course read
  function tickState(m) {
    const read = receipts.read[m.id] || 0;
    if (receipts.audience && read >= receipts.audience) return "read-all";
    return read > 0 ? "read-some" : "sent";
  }
  function ticksHtml(m) {
    if (!m.mine || m.deleted) return "";
    const state = tickState(m);
    const label = { sent: "נשלחה", "read-some": "חלק מהקורס קרא", "read-all": "כולם קראו" }[state];
    return `<span class="ticks ${state}" data-ticks="${m.id}" role="img" aria-label="${label}" title="${label}">${tickSvg(state)}</span>`;
  }
  function tickSvg(state) {
    const one = '<path d="M1.6 6.3 4.7 9.3 10.8 1.9"/>';
    const two = '<path d="M1.2 6.3 4.3 9.3 10.4 1.9"/><path d="M7.6 8.6 8.3 9.3 14.4 1.9"/>';
    return `<svg viewBox="0 0 16 11" width="17" height="12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${state === "sent" ? one : two}</svg>`;
  }

  function renderPoll(p) {
    const total = p.total || 0;
    const canVote = p.can_vote; // everyone in the course, except whoever created the poll
    const rows = p.options.map((o) => {
      const pct = total ? Math.round((o.votes / total) * 100) : 0;
      const chosen = p.my_vote === o.id;
      const tag = canVote ? "button" : "div";
      return `<${tag} class="poll-opt${chosen ? " chosen" : ""}" ${canVote ? `type="button" data-vote="${o.id}" data-poll="${p.id}"` : ""}>
          <span class="poll-radio" aria-hidden="true"></span>
          <span class="poll-text">${esc(o.text)}</span>
          <span class="poll-count">${o.votes}</span>
          <span class="poll-bar"><span style="transform:scaleX(${pct / 100})"></span></span>
        </${tag}>`;
    }).join("");
    const choose = canVote ? (p.my_vote ? "אפשר לשנות את הבחירה. " : "בחר תשובה אחת. ") : "";
    const privacy = p.anonymous ? "ההצבעה אנונימית" : "ההצבעה גלויה: כולם רואים מי בחר מה";
    const totalText = total === 1 ? "הצבעה אחת" : total + " הצבעות";
    const footer = !p.anonymous && total
      ? `<button type="button" class="poll-voters" data-voters="${p.id}">${totalText}. הצג מי הצביע</button>`
      : `<div class="poll-total">${totalText}</div>`;
    return `<div class="poll">
        <div class="poll-q">${esc(p.question)}</div>
        <div class="poll-hint">${choose}${privacy}</div>
        <div class="poll-opts">${rows}</div>
        ${footer}
      </div>`;
  }

  function renderMessage(m) {
    const who = m.mine
      ? (m.anonymous && !m.deleted ? `<div class="who who-anon">נשלח כאנונימי</div>` : "")
      : `<div class="who${m.anonymous ? " who-anon" : ""}">${esc(m.sender_name)}${m.sender_is_lecturer ? ' <span class="who-badge">מרצה</span>' : ""}</div>`;
    const pin = m.pinned
      ? `<span class="msg-pin" title="הודעה נעוצה" aria-label="נעוצה"><svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><path d="M15.5 3.5 20.5 8.5l-2.2.8-3.4 3.4.4 4.6-1.8 1.8-3.9-3.9L5 20l-1-1 4.8-4.6-3.9-3.9 1.8-1.8 4.6.4 3.4-3.4Z" fill="currentColor"/></svg></span>`
      : "";
    const star = m.starred
      ? `<span class="msg-star" title="מסומנת בכוכב" aria-label="מסומנת בכוכב">★</span>`
      : "";
    const meta = `<span class="meta">${star}${pin}<span class="time">${fmtTime(m.created_at)}</span>${ticksHtml(m)}</span>`;

    if (m.deleted) {
      return `<div class="msg ${m.mine ? "mine" : "theirs"} deleted" id="msg-${m.id}" data-id="${m.id}">
          <div class="bubble">${who}<div class="text deleted-text">⊘ ${m.mine ? "מחקת את ההודעה" : "ההודעה נמחקה"}</div>${meta}</div>
        </div>`;
    }

    const quote = m.reply_to
      ? `<button type="button" class="quote" data-jump="${m.reply_to.id}"><strong>${esc(m.reply_to.sender_name)}</strong><span>${esc(m.reply_to.body)}</span></button>`
      : "";
    const body = m.poll ? renderPoll(m.poll) : `<div class="text" dir="auto">${esc(m.body)}</div>`;
    const r = m.reactions;
    const summary = r.summary.length
      ? `<button type="button" class="reactions" data-who="${m.id}" aria-label="מי הגיב">${r.summary.map(([e, n]) => `<span>${e}${n > 1 ? ` ${n}` : ""}</span>`).join("")}</button>`
      : "";
    return `<div class="msg ${m.mine ? "mine" : "theirs"}${m.poll ? " has-poll" : ""}" id="msg-${m.id}" data-id="${m.id}">
        <div class="bubble" tabindex="0">
          ${who}${quote}${body}${meta}
          <span class="msg-tools">
            <button type="button" class="msg-tool" data-open="react" aria-label="הוסף תגובה">☺</button>
            <button type="button" class="msg-tool" data-open="menu" aria-label="אפשרויות">
              <svg viewBox="0 0 12 8" width="11" height="8" aria-hidden="true"><path d="M1 1.5l5 5 5-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </button>
          </span>
        </div>
        ${summary}
      </div>`;
  }

  function upsert(m) {
    messages.set(m.id, m);
    const html = renderMessage(m);
    const existing = document.getElementById("msg-" + m.id);
    if (existing) { existing.outerHTML = html; return; }
    // keep id order: older messages loaded for a search result go to the right place
    const after = [...list.querySelectorAll(".msg")].find((el) => Number(el.dataset.id) > m.id);
    if (after) after.insertAdjacentHTML("beforebegin", html);
    else list.insertAdjacentHTML("beforeend", html);
  }

  // ---------- day separators: היום / אתמול / weekday / full date, like WhatsApp ----------
  const dayKey = (ts) => { const d = new Date(ts * 1000); return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`; };
  function dayLabel(ts) {
    const d = new Date(ts * 1000);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const day = new Date(d); day.setHours(0, 0, 0, 0);
    const diff = Math.round((today - day) / 86400000);
    if (diff === 0) return "היום";
    if (diff === 1) return "אתמול";
    if (diff > 1 && diff < 7) return d.toLocaleDateString("he-IL", { weekday: "long" });
    const opts = { day: "numeric", month: "long" };
    if (d.getFullYear() !== today.getFullYear()) opts.year = "numeric";
    return d.toLocaleDateString("he-IL", opts);
  }
  // sticky day bars pile up at the top; only the last one that reached the top stays visible, like WhatsApp
  function syncStuckDays() {
    // stuck bars sit at the scroller top + its padding + the sticky offset (about 20px); 40px leaves room for that
    const top = scroller.getBoundingClientRect().top + (parseFloat(getComputedStyle(scroller).paddingTop) || 0) + 30;
    const bars = [...list.querySelectorAll(".day-divider")];
    let current = -1;
    bars.forEach((b, i) => { if (b.getBoundingClientRect().top <= top) current = i; });
    bars.forEach((b, i) => b.classList.toggle("covered", i < current));
  }
  scroller.addEventListener("scroll", syncStuckDays, { passive: true });

  function renderDays() {
    list.querySelectorAll(".day-divider").forEach((el) => el.remove());
    let last = null;
    list.querySelectorAll(".msg").forEach((el) => {
      const m = messages.get(Number(el.dataset.id));
      if (!m) return;
      const key = dayKey(m.created_at);
      if (key !== last) {
        el.insertAdjacentHTML("beforebegin", `<div class="day-divider" role="separator"><span>${dayLabel(m.created_at)}</span></div>`);
        last = key;
      }
    });
    syncStuckDays();
  }

  function updateTicks() {
    list.querySelectorAll("[data-ticks]").forEach((el) => {
      const m = messages.get(Number(el.dataset.ticks));
      if (!m) return;
      const fresh = ticksHtml(m);
      if (fresh && !el.classList.contains(tickState(m))) el.outerHTML = fresh;
    });
  }

  const nearBottom = () => scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
  const scrollToBottom = (smooth) => {
    scroller.scrollTo({ top: scroller.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    if (!smooth) syncStuckDays(); // an instant jump may not fire a scroll event
  };

  // ---------- read receipts: the chat counts as read while it is on screen ----------
  new IntersectionObserver((entries) => {
    chatVisible = entries.some((e) => e.isIntersecting);
    markRead();
  }, { threshold: 0.3 }).observe(scroller);

  async function markRead() {
    if (!active || !chatVisible || document.hidden || !messages.size) return;
    const maxId = Math.max(...messages.keys());
    if (maxId <= lastMarked) return;
    lastMarked = maxId;
    try { await Model.api(readUrl, { json: { up_to: maxId } }); } catch (_) { lastMarked = 0; }
  }

  // ---------- polling ----------
  async function refresh(first) {
    clearTimeout(timer);
    try {
      const stick = first || nearBottom();
      const d = await Model.api(listUrl + (since ? `?since=${since}` : ""));
      since = d.now;
      receipts = d.receipts || receipts;
      applyLock(!!d.locked);
      renderPinned(d.pinned || []);
      let added = false;
      d.messages.forEach((m) => {
        if (!messages.has(m.id)) added = true;
        upsert(m);
      });
      if (added || first) renderDays();
      updateTicks();
      empty.hidden = messages.size > 0;
      if (added && stick) scrollToBottom(!first);
      else if (added && !first) noteNew(d.messages.filter((m) => !m.mine).length);
      status.textContent = "";
      markRead();
    } catch (err) {
      status.textContent = err.status === 401 ? "צריך להתחבר מחדש" : "אין חיבור. מנסה שוב";
    }
    if (!document.hidden && active) timer = setTimeout(refresh, POLL_MS);
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && active) refresh();
    else clearTimeout(timer);
  });

  // ---------- composer ----------
  const sendBtn = document.getElementById("chat-send");
  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(140, input.scrollHeight) + "px";
    // a scrollbar only once the message really is taller than the box
    input.style.overflowY = input.scrollHeight > 140 ? "auto" : "hidden";
    // the send button wakes up only when there is something to send
    const ready = input.value.trim().length > 0;
    if (ready !== sendBtn.classList.contains("ready")) {
      sendBtn.classList.toggle("ready", ready);
      sendBtn.disabled = !ready;
    }
  }
  input.addEventListener("input", autosize);

  // ---------- emoji keyboard ----------
  const EMOJI = [
    ["😀", "סמיילים", "😀 😃 😄 😁 😆 😅 🤣 😂 🙂 🙃 😉 😊 😇 🥰 😍 🤩 😘 😋 😛 😜 🤪 😝 🤗 🤭 🤫 🤔 🤐 🤨 😐 😑 😶 😏 😒 🙄 😬 😌 😔 😪 😴 😷 🤒 🤕 🤢 🥵 🥶 🥴 😵 🤯 🤠 🥳 😎 🤓 🧐 😕 😟 🙁 😮 😯 😲 😳 🥺 😦 😧 😨 😰 😥 😢 😭 😱 😖 😣 😞 😓 😩 😫 🥱 😤 😡 😠 🤬 😈 💀 🤡 👻 🤖"],
    ["👍", "ידיים", "👍 👎 👌 🤌 🤏 ✌️ 🤞 🤟 🤘 🤙 👈 👉 👆 👇 ☝️ ✋ 🤚 🖐️ 🖖 👋 👏 🙌 👐 🤲 🤝 🙏 ✍️ 💪 🫶 👀 🧠"],
    ["❤️", "לבבות", "❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 💔 ❣️ 💕 💞 💓 💗 💖 💘 💝 💯 💢 💥 💫 💦 💤"],
    ["📚", "לימודים", "📚 📖 📝 ✏️ 🖊️ 📎 📌 📅 📆 🗓️ ⏰ ⏳ 💻 🖥️ ⌨️ 🖱️ 📱 📊 📈 📉 🧮 🔬 🧪 🎓 🏫 💡 🔍 📢 📣 🔔 ✅ ☑️ ❌ ❓ ❗ ⚠️ 🆗 🆕"],
    ["🎉", "חגיגות", "🎉 🎊 🥳 🎈 🎁 🏆 🥇 🥈 🥉 🏅 ⭐ 🌟 ✨ 🔥 ⚡ 🌈 ☀️ 🌙 ☕ 🍕 🍔 🍟 🌮 🍩 🍪 🎂 🍫 🍿 🥤 🍻"],
    ["🐶", "חיות", "🐶 🐱 🐭 🐹 🐰 🦊 🐻 🐼 🐨 🐯 🦁 🐮 🐷 🐸 🐵 🙈 🙉 🙊 🐔 🐧 🐦 🦄 🐝 🦋 🐢 🐍 🐙 🐬 🐳"],
  ];
  const RECENT_KEY = "moodleplus.recentEmoji";
  const panel = document.getElementById("emoji-panel");
  const tabs = document.getElementById("emoji-tabs");
  const grid = document.getElementById("emoji-grid");
  const emojiToggle = document.getElementById("emoji-toggle");
  let caret = 0;

  function recent() {
    try { return JSON.parse(localStorage.getItem(RECENT_KEY)) || []; } catch (_) { return []; }
  }
  function remember(e) {
    const list = [e, ...recent().filter((x) => x !== e)].slice(0, 24);
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch (_) {}
  }
  function groups() {
    const r = recent();
    return (r.length ? [["🕘", "בשימוש לאחרונה", r.join(" ")]] : []).concat(EMOJI);
  }
  function showGroup(i) {
    const g = groups();
    tabs.querySelectorAll("button").forEach((b, j) => b.setAttribute("aria-selected", String(j === i)));
    grid.innerHTML = `<div class="emoji-title">${g[i][1]}</div>` +
      g[i][2].split(" ").map((e) => `<button type="button" data-insert="${e}" aria-label="${e}">${e}</button>`).join("");
    grid.scrollTop = 0;
  }
  function openPanel() {
    tabs.innerHTML = groups().map((g, i) => `<button type="button" role="tab" data-tab="${i}" title="${g[1]}" aria-label="${g[1]}">${g[0]}</button>`).join("");
    showGroup(0);
    panel.hidden = false;
    emojiToggle.setAttribute("aria-expanded", "true");
    emojiToggle.classList.add("on");
  }
  function closePanel() {
    panel.hidden = true;
    emojiToggle.setAttribute("aria-expanded", "false");
    emojiToggle.classList.remove("on");
  }
  // remember where the caret was, so emoji go into the right place even after focus moved
  ["keyup", "click", "input", "select"].forEach((ev) =>
    input.addEventListener(ev, () => { caret = input.selectionStart ?? input.value.length; }));
  emojiToggle.addEventListener("click", () => (panel.hidden ? openPanel() : closePanel()));
  tabs.addEventListener("click", (e) => {
    const b = e.target.closest("[data-tab]");
    if (b) showGroup(Number(b.dataset.tab));
  });
  grid.addEventListener("click", (e) => {
    const b = e.target.closest("[data-insert]");
    if (!b) return;
    const em = b.dataset.insert;
    const pos = Math.min(caret, input.value.length);
    input.value = input.value.slice(0, pos) + em + input.value.slice(pos);
    caret = pos + em.length;
    remember(em);
    autosize();
    // on a phone, focusing would pop the system keyboard over the emoji panel
    if (window.matchMedia("(hover: hover)").matches) {
      input.focus();
      input.setSelectionRange(caret, caret);
    }
  });
  document.addEventListener("click", (e) => {
    if (!panel.hidden && !panel.contains(e.target) && !emojiToggle.contains(e.target)) closePanel();
  });
  input.addEventListener("focus", () => {
    if (!window.matchMedia("(hover: hover)").matches) closePanel(); // phone keyboard opened
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !("ontouchstart" in window)) {
      e.preventDefault();
      document.getElementById("composer").requestSubmit();
    }
  });

  const anon = document.getElementById("anon-toggle");
  if (anon) {
    anon.addEventListener("change", () => {
      document.getElementById("anon-note").hidden = !anon.checked;
      input.placeholder = anon.checked ? "הודעה אנונימית" : "כתוב הודעה";
    });
  }

  function setReply(m) {
    replyTo = m ? m.id : null;
    const box = document.getElementById("composer-reply");
    box.hidden = !m;
    if (m) {
      document.getElementById("reply-name").textContent = m.mine ? "אתה" : m.sender_name;
      document.getElementById("reply-body").textContent = m.poll ? "סקר: " + m.poll.question : m.body;
      input.focus();
    }
  }
  document.getElementById("reply-cancel").addEventListener("click", () => setReply(null));

  document.getElementById("composer").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    sendBtn.disabled = true;
    sendBtn.classList.add("sending");
    try {
      await Model.api(sendUrl, { json: { body: text, reply_to: replyTo, anonymous: !!(anon && anon.checked) } });
      input.value = "";
      caret = 0;
      closePanel();
      setReply(null);
      await refresh();
      scrollToBottom(true);
    } catch (err) {
      Model.toast(err.message, "error");
    } finally {
      sendBtn.classList.remove("sending");
      autosize();
      input.focus();
    }
  });

  // ---------- popover: emoji row and/or menu ----------
  // ---------- reactions: the six you used most recently, plus "+" for any emoji ----------
  const DEFAULT_REACTIONS = ["👍", "❤️", "😂", "👎", "😢", "🙏"];
  const RECENT_REACT_KEY = "moodleplus.recentReactions";
  const isPhone = window.matchMedia("(hover: none) and (pointer: coarse)").matches;

  function recentReactions(mine) {
    let saved = [];
    try { saved = JSON.parse(localStorage.getItem(RECENT_REACT_KEY)) || []; } catch (_) {}
    const list = [];
    for (const e of [mine, ...saved, ...DEFAULT_REACTIONS]) {   // your current reaction always shows
      if (e && !list.includes(e)) list.push(e);
      if (list.length === 6) break;
    }
    return list;
  }
  function rememberReaction(e) {
    let saved = [];
    try { saved = JSON.parse(localStorage.getItem(RECENT_REACT_KEY)) || []; } catch (_) {}
    try { localStorage.setItem(RECENT_REACT_KEY, JSON.stringify([e, ...saved.filter((x) => x !== e)].slice(0, 12))); } catch (_) {}
  }
  const plusButton = (attr) =>
    `<button type="button" class="react-more" ${attr} aria-label="אימוג׳י אחר" title="אימוג׳י אחר">
       <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>
     </button>`;
  function renderBar(mine) {
    bar.innerHTML = recentReactions(mine)
      .map((e) => `<button type="button" data-emoji="${e}" aria-label="הגב ${e}" class="${e === mine ? "active" : ""}">${e}</button>`)
      .join("") + plusButton("data-react-more");
  }

  async function react(id, emoji) {
    try {
      const d = await Model.api(`/api/messages/${id}/reactions`, { json: { emoji } });
      if (d.mine) rememberReaction(d.mine);
      const m = messages.get(id);
      if (m) m.reactions.mine = d.mine;
      await refresh();
      return d;
    } catch (err) { Model.toast(err.message, "error"); }
  }

  // "+" on a computer: the site's emoji keyboard, next to the message
  const reactPicker = document.getElementById("reaction-picker");
  const reactTabs = document.getElementById("reaction-tabs");
  const reactGrid = document.getElementById("reaction-grid");
  let pickFor = null;
  let pickDone = null;
  function showReactGroup(i) {
    const g = EMOJI[i];
    reactTabs.querySelectorAll("button").forEach((b, j) => b.setAttribute("aria-selected", String(j === i)));
    reactGrid.innerHTML = `<div class="emoji-title">${g[1]}</div>` +
      g[2].split(" ").map((e) => `<button type="button" data-pick="${e}" aria-label="${e}">${e}</button>`).join("");
    reactGrid.scrollTop = 0;
  }
  function openReactPicker(id, anchorEl, done) {
    pickFor = id;
    pickDone = done || null;
    reactTabs.innerHTML = EMOJI.map((g, i) => `<button type="button" role="tab" data-rtab="${i}" title="${g[1]}" aria-label="${g[1]}">${g[0]}</button>`).join("");
    showReactGroup(0);
    reactPicker.hidden = false;
    const host = root.getBoundingClientRect();
    const a = anchorEl.getBoundingClientRect();
    const h = reactPicker.offsetHeight;
    let top = a.top - host.top - h - 6;
    if (top < 4) top = Math.min(a.bottom - host.top + 6, host.height - h - 4);
    reactPicker.style.top = Math.max(4, top) + "px";
  }
  function closeReactPicker() { reactPicker.hidden = true; pickFor = null; pickDone = null; }
  reactTabs.addEventListener("click", (e) => {
    const b = e.target.closest("[data-rtab]");
    if (b) showReactGroup(Number(b.dataset.rtab));
  });
  reactGrid.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-pick]");
    if (!b || pickFor === null) return;
    const id = pickFor, done = pickDone;
    closeReactPicker();
    await react(id, b.dataset.pick);
    if (done) done();
  });
  document.addEventListener("click", (e) => {
    if (!reactPicker.hidden && !reactPicker.contains(e.target) && !e.target.closest("[data-react-more], [data-who-more]")) closeReactPicker();
  });

  // "+" on a phone: focus a hidden field so the phone's own keyboard opens; the first emoji typed is sent
  const nativeInput = document.getElementById("native-emoji");
  let nativeFor = null;
  let nativeDone = null;
  function openNativeKeyboard(id, done) {
    nativeFor = id;
    nativeDone = done || null;
    nativeInput.value = "";
    nativeInput.focus();   // must run inside the tap itself, or iOS will not open the keyboard
    Model.toast("בחר אימוג׳י מהמקלדת (כפתור הסמיילי במקלדת)");
  }
  function firstEmoji(text) {
    const parts = window.Intl && Intl.Segmenter
      ? [...new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(text)].map((s) => s.segment)
      : Array.from(text);
    return parts.find((p) => /\p{Extended_Pictographic}|\p{Regional_Indicator}/u.test(p)) || null;
  }
  nativeInput.addEventListener("input", async () => {
    const emoji = firstEmoji(nativeInput.value);
    nativeInput.value = "";
    if (!emoji || nativeFor === null) return;   // letters are ignored: only an emoji counts
    const id = nativeFor, done = nativeDone;
    nativeFor = null; nativeDone = null;
    nativeInput.blur();
    await react(id, emoji);
    if (done) done();
  });
  nativeInput.addEventListener("blur", () => { nativeFor = null; nativeDone = null; });

  function moreReactions(id, anchorEl, done) {
    if (isPhone) openNativeKeyboard(id, done);
    else openReactPicker(id, anchorEl, done);
  }

  function openPop(msgEl, { react, menuOpen }) {
    const m = messages.get(Number(msgEl.dataset.id));
    if (!m || m.deleted) return;
    popFor = m.id;
    bar.hidden = !react;
    menu.hidden = !menuOpen;
    confirmBox.hidden = true;
    renderBar(m.reactions.mine);
    menu.querySelector('[data-action="info"]').hidden = !m.mine;
    const pinItem = menu.querySelector('[data-action="pin"]');
    pinItem.hidden = root.dataset.canPin !== "1";
    pinItem.textContent = m.pinned ? "בטל נעיצה" : "נעץ הודעה";
    menu.querySelector('[data-action="star"]').textContent = m.starred ? "הסר כוכב" : "סמן בכוכב";
    menu.querySelector('[data-action="delete"]').hidden = !m.can_delete;
    pop.hidden = false;
    msgEl.classList.add("active");
    placePop();
  }
  function placePop() {
    // look the message up again: polling may have re-rendered it since the popover opened
    const msgEl = popFor === null ? null : document.getElementById("msg-" + popFor);
    if (!msgEl) return;
    const bubble = msgEl.querySelector(".bubble").getBoundingClientRect();
    const host = root.getBoundingClientRect();
    const h = pop.offsetHeight;
    let top = bubble.top - host.top - h - 6;
    if (top < 4) top = bubble.bottom - host.top + 6; // not enough room above: open below
    pop.style.top = Math.max(4, top) + "px";
    const isMine = msgEl.classList.contains("mine");
    pop.style.left = isMine ? "12px" : "auto";
    pop.style.right = isMine ? "auto" : "12px";
    pop.classList.toggle("align-left", isMine);
  }
  function closePop() {
    pop.hidden = true;
    list.querySelectorAll(".msg.active").forEach((el) => el.classList.remove("active"));
    popFor = null;
  }

  // phone: long-press opens emoji row + menu together
  let pressTimer = null;
  let pressed = false;
  list.addEventListener("touchstart", (e) => {
    const msgEl = e.target.closest(".msg");
    if (!msgEl || e.target.closest("button")) return;
    pressed = false;
    pressTimer = setTimeout(() => {
      pressed = true;
      openPop(msgEl, { react: true, menuOpen: true });
      navigator.vibrate?.(10);
    }, 450);
  }, { passive: true });
  ["touchend", "touchmove", "touchcancel"].forEach((ev) =>
    list.addEventListener(ev, () => clearTimeout(pressTimer), { passive: true }));
  list.addEventListener("contextmenu", (e) => {
    const msgEl = e.target.closest(".msg");
    if (msgEl && !msgEl.classList.contains("deleted")) { e.preventDefault(); openPop(msgEl, { react: true, menuOpen: true }); }
  });

  pop.addEventListener("click", async (e) => {
    const btn = e.target.closest("button");
    if (!btn || popFor === null) return;
    // delete asks inside the popover itself, not with a browser dialog
    if (btn.dataset.action === "delete" || btn.dataset.action === "cancel-delete") {
      const asking = btn.dataset.action === "delete";
      confirmBox.hidden = !asking;
      menu.hidden = asking;
      bar.hidden = true;
      placePop();
      return;
    }
    const id = popFor;
    const m = messages.get(id);
    if (btn.hasAttribute("data-react-more")) {
      // anchor the picker to the message before the popover closes
      const msgEl = document.getElementById("msg-" + id);
      closePop();
      moreReactions(id, msgEl ? msgEl.querySelector(".bubble") : btn);
      return;
    }
    closePop();
    if (btn.dataset.emoji) {
      await react(id, btn.dataset.emoji);
    } else if (btn.dataset.action === "reply") {
      setReply(m);
    } else if (btn.dataset.action === "info") {
      showInfo(m);
    } else if (btn.dataset.action === "star") {
      try {
        await Model.api(`/api/messages/${id}/star`, { json: { starred: !m.starred } });
        m.starred = !m.starred;
        upsert(m);
        Model.toast(m.starred ? "ההודעה סומנה בכוכב" : "הכוכב הוסר");
        if (starredOpen) showStarred();
      } catch (err) { Model.toast(err.message, "error"); }
    } else if (btn.dataset.action === "pin") {
      try {
        const d = await Model.api(`/api/messages/${id}/pin`, { json: { pinned: !m.pinned } });
        if (d.replaced) Model.toast("אפשר לנעוץ עד 3 הודעות, אז הנעוצה הישנה ביותר הוסרה");
        else Model.toast(d.pinned ? "ההודעה ננעצה" : "הנעיצה בוטלה");
        await refresh();
      } catch (err) { Model.toast(err.message, "error"); }
    } else if (btn.dataset.action === "confirm-delete") {
      try {
        await Model.api(`/api/messages/${id}`, { method: "DELETE" });
        refresh();
      } catch (err) { Model.toast(err.message, "error"); }
    }
  });

  document.addEventListener("click", (e) => {
    if (!pop.hidden && !pop.contains(e.target) && !e.target.closest("[data-open]") && !pressed) closePop();
    pressed = false;
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePop(); });
  scroller.addEventListener("scroll", closePop, { passive: true });

  async function showInfo(m) {
    try {
      const d = await Model.api(`/api/messages/${m.id}/info`);
      document.getElementById("info-preview").innerHTML = m.poll
        ? `<strong>סקר:</strong> ${esc(m.poll.question)}`
        : esc(m.body);
      document.querySelector("#info-dialog .info-head .ticks").innerHTML = tickSvg("read-all");
      document.getElementById("info-count").textContent = d.read_by.length ? `(${d.read_by.length})` : "";
      document.getElementById("info-list").innerHTML = d.read_by.length
        ? d.read_by.map((r) => `<li><span class="grow">${esc(r.name)}</span><span class="xsmall muted">${fmtWhen(r.read_at)}</span></li>`).join("")
        : `<li class="muted small">עוד אף אחד לא קרא</li>`;
      document.getElementById("info-unread").textContent = d.unread
        ? `עוד לא קראו: ${d.unread} מתוך ${d.audience}`
        : "כל חברי הקורס קראו את ההודעה";
      document.getElementById("info-dialog").showModal();
    } catch (err) { Model.toast(err.message, "error"); }
  }

  list.addEventListener("click", async (e) => {
    const opener = e.target.closest("[data-open]");
    if (opener) {
      const msgEl = opener.closest(".msg");
      const wantMenu = opener.dataset.open === "menu";
      const alreadyOpen = popFor === Number(msgEl.dataset.id) && (wantMenu ? !menu.hidden : !bar.hidden);
      if (alreadyOpen) return closePop();
      return openPop(msgEl, { react: !wantMenu, menuOpen: wantMenu });
    }

    const jump = e.target.closest("[data-jump]");
    if (jump) {
      const target = document.getElementById("msg-" + jump.dataset.jump);
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        target.classList.remove("flash"); void target.offsetWidth; target.classList.add("flash");
      }
      return;
    }

    const who = e.target.closest("[data-who]");
    if (who) {
      whoFor = Number(who.dataset.who);
      await fillWho();
      document.getElementById("who-dialog").showModal();
      return;
    }

    const votersBtn = e.target.closest("[data-voters]");
    if (votersBtn) {
      const m = [...messages.values()].find((x) => x.poll && x.poll.id === Number(votersBtn.dataset.voters));
      if (!m) return;
      document.getElementById("voters-title").textContent = m.poll.question;
      document.getElementById("voters-list").innerHTML = m.poll.options.map((o) => `
        <section>
          <h3><span>${esc(o.text)}</span><span class="muted">${o.votes}</span></h3>
          ${o.voters && o.voters.length
            ? `<ul>${o.voters.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>`
            : `<p class="muted small">אף אחד</p>`}
        </section>`).join("");
      document.getElementById("voters-dialog").showModal();
      return;
    }

    const vote = e.target.closest("[data-vote]");
    if (vote) {
      try {
        const d = await Model.api(`/api/polls/${vote.dataset.poll}/vote`, { json: { option_id: Number(vote.dataset.vote) } });
        const msg = [...messages.values()].find((m) => m.poll && m.poll.id === d.poll.id);
        if (msg) { msg.poll = d.poll; upsert(msg); }
      } catch (err) { Model.toast(err.message, "error"); }
    }
  });

  // ---------- search: on the server, so it finds old messages that are not loaded yet ----------
  const searchOpen = document.getElementById("chat-search-open");
  const searchBar = document.getElementById("chat-search-bar");
  const searchInput = document.getElementById("chat-search-input");
  const searchResults = document.getElementById("chat-search-results");
  let searchTimer = null;
  let searchSeq = 0;

  function highlight(text, q) {
    const safe = esc(text);
    if (!q) return safe;
    const needle = esc(q).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return safe.replace(new RegExp(needle, "gi"), (s) => `<mark>${s}</mark>`);
  }
  // show the words around the match, not the start of a long message
  function snippet(text, q) {
    const i = text.toLowerCase().indexOf(q.toLowerCase());
    if (i < 40) return text.slice(0, 140);
    return "…" + text.slice(i - 30, i - 30 + 140);
  }

  function openSearch() {
    if (!searchBar) return;
    searchBar.hidden = false;
    searchBar.closest(".chat-bar").classList.add("searching");
    searchInput.focus();
  }
  function closeSearch() {
    starredOpen = false;
    if (!searchBar) return;
    searchBar.hidden = true;
    searchBar.closest(".chat-bar").classList.remove("searching");
    searchInput.value = "";
    searchResults.hidden = true;
    searchResults.innerHTML = "";
  }

  async function runSearch() {
    const q = searchInput.value.trim();
    const seq = ++searchSeq;
    if (q.length < 2) { searchResults.hidden = q.length === 0; searchResults.innerHTML = q ? `<p class="search-empty">הקלד לפחות שתי אותיות</p>` : ""; return; }
    try {
      const d = await Model.api(`${root.dataset.searchUrl}?q=${encodeURIComponent(q)}`);
      if (seq !== searchSeq) return; // a newer search already started
      searchResults.hidden = false;
      searchResults.innerHTML = d.results.length
        ? `<p class="search-count">${d.results.length === 1 ? "תוצאה אחת" : d.results.length + " תוצאות"}</p>` +
          d.results.map((r) => `
            <button type="button" class="search-hit" data-hit="${r.id}">
              <span class="search-hit-top"><strong>${esc(r.mine ? "אתה" : r.sender_name)}</strong><span>${dayLabel(r.created_at)} ${fmtTime(r.created_at)}</span></span>
              <span class="search-hit-text">${r.is_poll ? "סקר: " : ""}${highlight(snippet(r.text, q), q)}</span>
            </button>`).join("")
        : `<p class="search-empty">לא נמצאו הודעות עם ״${esc(q)}״</p>`;
    } catch (err) { Model.toast(err.message, "error"); }
  }

  async function jumpTo(id) {
    if (!document.getElementById("msg-" + id)) {
      // older than what is loaded: fetch from that message onward
      try {
        const d = await Model.api(`${listUrl}?from_id=${id}`);
        d.messages.forEach(upsert);
        renderDays();
        updateTicks();
      } catch (err) { return Model.toast(err.message, "error"); }
    }
    closeSearch();
    const target = document.getElementById("msg-" + id);
    if (!target) return Model.toast("ההודעה כבר לא קיימת", "error");
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.remove("flash"); void target.offsetWidth; target.classList.add("flash");
  }

  if (searchOpen) {
    searchOpen.addEventListener("click", openSearch);
    document.getElementById("chat-search-close").addEventListener("click", closeSearch);
    searchBar.addEventListener("submit", (e) => { e.preventDefault(); clearTimeout(searchTimer); runSearch(); });
    searchInput.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 250); });
    searchInput.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSearch(); });
    searchResults.addEventListener("click", (e) => {
      const hit = e.target.closest("[data-hit]");
      if (hit) jumpTo(Number(hit.dataset.hit));
    });
  }

  // ---------- pinned messages bar (everyone sees it; only the course lecturer pins) ----------
  const pinnedBar = document.getElementById("pinned-bar");
  let pinnedList = [];
  let pinnedIndex = 0;
  function renderPinned(list) {
    const ids = list.map((p) => p.id).join(",");
    if (ids !== pinnedList.map((p) => p.id).join(",")) pinnedIndex = 0; // the set changed: start from the newest
    pinnedList = list;
    pinnedBar.hidden = !list.length;
    if (!list.length) return;
    pinnedIndex = Math.min(pinnedIndex, list.length - 1);
    const p = list[pinnedIndex];
    document.getElementById("pinned-who").textContent = (p.mine ? "אתה" : p.sender_name) + ": ";
    document.getElementById("pinned-body").textContent = p.text;
    document.getElementById("pinned-count").textContent = list.length > 1 ? `${pinnedIndex + 1}/${list.length}` : "";
  }
  pinnedBar.addEventListener("click", async () => {
    if (!pinnedList.length) return;
    const p = pinnedList[pinnedIndex];
    await jumpTo(p.id);
    // like WhatsApp: the next tap shows the next pinned message
    if (pinnedList.length > 1) { pinnedIndex = (pinnedIndex + 1) % pinnedList.length; renderPinned(pinnedList); }
  });

  // ---------- mute students: only the lecturer and the admin can post ----------
  // the server enforces it; here we only reflect the state (it arrives with every poll)
  const isStudent = root.dataset.isStudent === "1";
  const lockedBar = document.getElementById("chat-locked-bar");
  const composer = document.getElementById("composer");
  const muteBtn = document.getElementById("chat-mute");
  let locked = root.dataset.locked === "1";
  function applyLock(value) {
    if (value === locked && lockedBar.hidden === !value) return;
    locked = value;
    lockedBar.hidden = !locked;
    if (isStudent) {
      composer.hidden = locked;
      if (locked) { closePanel(); setReply(null); }
    }
    if (muteBtn) {
      muteBtn.setAttribute("aria-pressed", String(locked));
      document.getElementById("chat-mute-label").textContent = locked ? "בטל השתקה" : "השתק סטודנטים";
    }
  }
  if (muteBtn) {
    muteBtn.addEventListener("click", async () => {
      muteBtn.disabled = true;
      try {
        const d = await Model.api(root.dataset.lockUrl, { json: { locked: !locked } });
        applyLock(d.locked);
        Model.toast(d.locked ? "הסטודנטים מושתקים. רק אתה ומנהל המערכת יכולים לשלוח" : "ההשתקה בוטלה. כולם יכולים לכתוב");
      } catch (err) { Model.toast(err.message, "error"); }
      muteBtn.disabled = false;
    });
  }

  // ---------- "who reacted" dialog: also lets you change or remove your own reaction ----------
  let whoFor = null;
  async function fillWho() {
    try {
      const d = await Model.api(`/api/messages/${whoFor}/reactions`);
      const mine = messages.get(whoFor)?.reactions.mine || null;
      document.getElementById("who-emoji").innerHTML = recentReactions(mine)
        .map((e) => `<button type="button" data-dialog-emoji="${e}" aria-label="${e}" class="${e === mine ? "active" : ""}">${e}</button>`)
        .join("") + plusButton("data-who-more");
      document.getElementById("who-mine-label").textContent = mine ? "התגובה שלך. לחיצה על אותו אימוג׳י מסירה אותה" : "הוסף תגובה";
      document.getElementById("who-list").innerHTML = d.reactions.length
        ? d.reactions.map((r) => `<li><span style="font-size:22px">${r.emoji}</span><span class="grow">${esc(r.name)}</span></li>`).join("")
        : `<li class="muted small">אין תגובות</li>`;
    } catch (err) { Model.toast(err.message, "error"); }
  }
  document.getElementById("who-emoji").addEventListener("click", async (e) => {
    if (whoFor === null) return;
    const id = whoFor;
    const more = e.target.closest("[data-who-more]");
    if (more) {
      // the dialog is modal, so the site picker cannot open over it: close it, pick, reopen
      document.getElementById("who-dialog").close();
      const msgEl = document.getElementById("msg-" + id);
      moreReactions(id, msgEl ? msgEl.querySelector(".bubble") : more, async () => {
        whoFor = id;
        await fillWho();
        document.getElementById("who-dialog").showModal();
      });
      return;
    }
    const b = e.target.closest("[data-dialog-emoji]");
    if (!b) return;
    await react(id, b.dataset.dialogEmoji);
    await fillWho();
  });

  // ---------- poll creation (lecturer) ----------
  const pollForm = document.getElementById("poll-form");
  if (pollForm) {
    const box = document.getElementById("poll-options");
    const MAX = 6;
    function addRow() {
      const n = box.querySelectorAll("input").length;
      if (n >= MAX) return;
      const inp = document.createElement("input");
      inp.type = "text";
      inp.maxLength = 100;
      inp.placeholder = `תשובה ${n + 1}`;
      inp.setAttribute("aria-label", `תשובה ${n + 1}`);
      box.appendChild(inp);
    }
    const anonToggle = document.getElementById("poll-anonymous");
    const anonHint = document.getElementById("poll-anon-hint");
    function syncAnonHint() {
      anonHint.textContent = anonToggle.checked
        ? "כולם יראו רק כמה הצביעו לכל תשובה, בלי שמות."
        : "כולם יוכלו לראות מי הצביע לכל תשובה.";
    }
    anonToggle.addEventListener("change", syncAnonHint);
    function reset() {
      box.querySelectorAll("input").forEach((i) => i.remove());
      addRow(); addRow();
      document.getElementById("poll-question").value = "";
      anonToggle.checked = true;
      syncAnonHint();
    }
    box.addEventListener("input", () => {
      const inputs = [...box.querySelectorAll("input")];
      if (inputs[inputs.length - 1].value.trim()) addRow();
    });
    pollForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const options = [...box.querySelectorAll("input")].map((i) => i.value.trim()).filter(Boolean);
      try {
        await Model.api(pollUrl, {
          json: { question: document.getElementById("poll-question").value, options, anonymous: anonToggle.checked },
        });
        document.getElementById("poll-dialog").close();
        reset();
        await refresh();
        scrollToBottom(true);
      } catch (err) { Model.toast(err.message, "error"); }
    });
    reset();
  }

  refresh(true);

  // ---------- back to the newest messages: a small round arrow while you read older ones ----------
  const jumpBtn = document.getElementById("jump-latest");
  const jumpCount = document.getElementById("jump-count");
  let unseenNew = 0;
  function noteNew(n) {
    if (!n) return;
    unseenNew += n;
    jumpCount.textContent = unseenNew > 99 ? "99+" : String(unseenNew);
    jumpCount.hidden = false;
  }
  function syncJump() {
    const far = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight > 320;
    jumpBtn.hidden = !far;
    if (!far) { unseenNew = 0; jumpCount.hidden = true; }
  }
  scroller.addEventListener("scroll", syncJump, { passive: true });
  jumpBtn.addEventListener("click", () => scrollToBottom(true));

  // ---------- the header's "more" menu ----------
  const moreBtn = document.getElementById("chat-more-open");
  const moreMenu = document.getElementById("chat-more-menu");
  const openMore = (on) => { moreMenu.hidden = !on; moreBtn.setAttribute("aria-expanded", String(on)); };
  if (moreBtn) {
    moreBtn.addEventListener("click", () => openMore(moreMenu.hidden));
    document.addEventListener("click", (e) => { if (!moreMenu.hidden && !e.target.closest(".chat-more")) openMore(false); });
    moreMenu.addEventListener("keydown", (e) => { if (e.key === "Escape") { openMore(false); moreBtn.focus(); } });
    moreMenu.addEventListener("click", (e) => {
      const item = e.target.closest("[data-more]");
      if (!item) return;
      openMore(false);
      if (item.dataset.more === "starred") showStarred();
      else openTheme();
    });
  }

  // ---------- starred messages: your own bookmarks, in the same panel as search results ----------
  let starredOpen = false;
  async function showStarred() {
    try {
      const d = await Model.api(root.dataset.starredUrl);
      closeSearch();
      starredOpen = true;
      searchResults.hidden = false;
      searchResults.innerHTML = `<div class="panel-title"><span>★ הודעות מסומנות בכוכב</span>
          <button type="button" class="chat-icon-btn" data-close-starred aria-label="סגור">✕</button></div>` +
        (d.results.length
          ? d.results.map((r) => `
            <button type="button" class="search-hit" data-hit="${r.id}">
              <span class="search-hit-top"><strong>${esc(r.mine ? "אתה" : r.sender_name)}</strong><span>${dayLabel(r.created_at)} ${fmtTime(r.created_at)}</span></span>
              <span class="search-hit-text">${r.is_poll ? "סקר: " : ""}${esc(r.text.slice(0, 160))}</span>
            </button>`).join("")
          : `<p class="search-empty">עוד לא סימנת הודעות. פתח את התפריט של הודעה ובחר ״סמן בכוכב״, והיא תחכה לך כאן.</p>`);
    } catch (err) { Model.toast(err.message, "error"); }
  }
  searchResults.addEventListener("click", (e) => {
    if (e.target.closest("[data-close-starred]")) closeSearch();
  });
  if (!searchOpen) {  // search may be missing; starred results still need to jump
    searchResults.addEventListener("click", (e) => {
      const hit = e.target.closest("[data-hit]");
      if (hit) jumpTo(Number(hit.dataset.hit));
    });
  }

  // ---------- wallpaper and the colour of my messages: preview, then "only here" or "all my chats" ----------
  const themeDialog = document.getElementById("theme-dialog");
  const preview = document.getElementById("theme-preview");
  const applyBtn = document.getElementById("theme-apply");
  const scopeAsk = document.getElementById("scope-ask");
  const themeActions = document.getElementById("theme-actions");
  const wallFile = document.getElementById("wall-file");
  const photoTile = document.getElementById("photo-tile");
  let pick = null;  // { wall, bubble, file, photo, reset }

  function markSwatches() {
    document.querySelectorAll("[data-wall-choice]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.wallChoice === pick.wall)));
    document.querySelectorAll("[data-bubble-choice]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.bubbleChoice === pick.bubble)));
    preview.dataset.wall = pick.wall;
    preview.dataset.bubble = pick.bubble;
    preview.style.setProperty("--wall-photo", pick.photo || root.style.getPropertyValue("--wall-photo") || "none");
    const changed = pick.wall !== root.dataset.wall || pick.bubble !== root.dataset.bubble || !!pick.file;
    applyBtn.disabled = !changed;
  }
  function askScope(on, question) {
    scopeAsk.hidden = !on;
    themeActions.hidden = on;
    if (on) {
      document.getElementById("scope-question").textContent = question;
      scopeAsk.querySelector('[data-scope="here"]').focus();
    }
  }
  function openTheme() {
    if (!themeDialog) return;
    pick = { wall: root.dataset.wall, bubble: root.dataset.bubble, file: null, photo: "", reset: false };
    const current = root.style.getPropertyValue("--wall-photo");
    photoTile.style.backgroundImage = current || "";
    askScope(false);
    markSwatches();
    themeDialog.showModal();
  }
  if (themeDialog) {
    themeDialog.addEventListener("click", (e) => {
      const w = e.target.closest("[data-wall-choice]");
      if (w) {
        if (w.dataset.wallChoice === "image" && !pick.file && !root.style.getPropertyValue("--wall-photo")) return wallFile.click();
        if (w.dataset.wallChoice === "image" && pick.wall === "image") return wallFile.click(); // tap again: another photo
        pick.wall = w.dataset.wallChoice;
        return markSwatches();
      }
      const b = e.target.closest("[data-bubble-choice]");
      if (b) { pick.bubble = b.dataset.bubbleChoice; markSwatches(); }
    });
    wallFile.addEventListener("change", () => {
      const file = wallFile.files[0];
      if (!file) return;
      if (file.size > 8 * 1024 * 1024) { wallFile.value = ""; return Model.toast("התמונה גדולה מדי. אפשר עד 8MB", "error"); }
      pick.file = file;
      pick.wall = "image";
      pick.photo = `url("${URL.createObjectURL(file)}")`;
      photoTile.style.backgroundImage = pick.photo;
      markSwatches();
    });
    applyBtn.addEventListener("click", () => { pick.reset = false; askScope(true, "איפה להחיל את השינוי?"); });
    document.getElementById("theme-reset").addEventListener("click", () => {
      pick.reset = true;
      askScope(true, "לחזור לרקע ולצבע של ברירת המחדל איפה?");
    });
    scopeAsk.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-scope]");
      if (!b) return;
      if (b.dataset.scope === "back") return askScope(false);
      if (scopeAsk.dataset.busy) return; // a second tap while saving must not save (and announce) twice
      scopeAsk.dataset.busy = "1";
      scopeAsk.querySelectorAll("button").forEach((x) => { x.disabled = true; });
      const scope = b.dataset.scope;
      try {
        let d;
        if (pick.reset) {
          d = await Model.api(root.dataset.themeUrl, { json: { scope, reset: true } });
        } else if (pick.file && pick.wall === "image") {
          const form = new FormData();
          form.append("scope", scope);
          form.append("wallpaper", "image");
          if (pick.bubble !== root.dataset.bubble) form.append("bubble", pick.bubble);
          form.append("image", pick.file);
          d = await Model.api(root.dataset.themeUrl, { method: "POST", body: form });
        } else {
          const body = { scope };
          if (pick.wall !== root.dataset.wall || scope === "all") body.wallpaper = pick.wall;
          if (pick.bubble !== root.dataset.bubble || scope === "all") body.bubble = pick.bubble;
          if (body.wallpaper === "image") delete body.wallpaper; // the photo you already have stays as it is
          d = await Model.api(root.dataset.themeUrl, { json: body });
        }
        root.dataset.wall = d.wallpaper;
        root.dataset.bubble = d.bubble;
        if (d.image_url) root.style.setProperty("--wall-photo", `url("${d.image_url}")`);
        else root.style.removeProperty("--wall-photo");
        themeDialog.close();
        Model.toast(pick.reset ? "חזרת לברירת המחדל" : scope === "all" ? "העיצוב נשמר לכל הצ׳אטים שלך" : "העיצוב נשמר לצ׳אט הזה");
      } catch (err) { Model.toast(err.message, "error"); }
      finally {
        delete scopeAsk.dataset.busy;
        scopeAsk.querySelectorAll("button").forEach((x) => { x.disabled = false; });
      }
    });
  }

  // ---------- glass header and input bar: the messages scroll underneath them, like WhatsApp ----------
  const page = document.querySelector(".chat-page");
  if (page) {
    const header = page.querySelector(".chat-bar");
    const h = (el) => (!el || el.hidden || getComputedStyle(el).display === "none" ? 0 : el.getBoundingClientRect().height);
    const measure = () => {
      const stick = nearBottom();
      const bar = h(header), pin = h(pinnedBar), comp = h(composer), lock = h(lockedBar);
      page.style.setProperty("--bar-h", bar + "px");
      page.style.setProperty("--top-h", bar + pin + "px");
      page.style.setProperty("--composer-h", comp + "px");
      page.style.setProperty("--bottom-h", comp + lock + "px");
      if (stick) scrollToBottom(false); // a taller input bar must not hide the newest message
    };
    const watch = new ResizeObserver(measure);
    [header, pinnedBar, composer, lockedBar].forEach((el) => el && watch.observe(el));
    measure();
  }

  // ---------- inside the course page ----------
  if (embedded) {
    const tell = (type, extra) => window.parent.postMessage({ type, ...extra }, location.origin);
    window.addEventListener("message", (e) => {
      if (e.origin !== location.origin || e.source !== window.parent) return;
      if (e.data?.type === "chat:open") {
        active = true;
        refresh();
      } else if (e.data?.type === "chat:hide") {
        active = false;
        clearTimeout(timer);
        closePop();
        closeSearch();
      }
    });
    document.querySelector("[data-chat-back]")?.addEventListener("click", (e) => { e.preventDefault(); tell("chat:close"); });
    // the side strip on a computer: its tabs belong to the course page underneath
    document.querySelectorAll(".tabbar-rail a").forEach((a) => {
      const url = new URL(a.href, location.href);
      if (!url.hash) return;
      a.addEventListener("click", (e) => { e.preventDefault(); tell("chat:tab", { hash: url.hash }); });
    });
    tell("chat:ready");
  }

  // ---------- phone: swipe a message to reply; swipe your own message the other way for its details ----------
  // in Hebrew (right to left) reply is a swipe to the left and details a swipe to the right, mirrored like WhatsApp
  const replyDir = getComputedStyle(document.documentElement).direction === "rtl" ? -1 : 1;
  const SWIPE_AT = 56, SWIPE_MAX = 76;
  const REPLY_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M10 7 5 12l5 5M5.5 12H14a5 5 0 0 1 5 5v1" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const INFO_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="M12 11v5M12 8h.01" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>';
  let swipe = null;
  list.addEventListener("touchstart", (e) => {
    const msgEl = e.target.closest(".msg");
    swipe = null;
    if (!msgEl || msgEl.classList.contains("deleted") || e.touches.length > 1 || e.target.closest("button, a, input")) return;
    const t = e.touches[0];
    swipe = { el: msgEl, bubble: msgEl.querySelector(".bubble"), x: t.clientX, y: t.clientY, dir: 0, mode: null, ready: false, hint: null };
  }, { passive: true });
  list.addEventListener("touchmove", (e) => {
    if (!swipe) return;
    const t = e.touches[0];
    const dx = t.clientX - swipe.x, dy = t.clientY - swipe.y;
    if (!swipe.mode) {
      if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
      swipe.mode = Math.abs(dx) > Math.abs(dy) * 1.4 ? "h" : "v";
      if (swipe.mode === "v") { swipe = null; return; }
      const m = messages.get(Number(swipe.el.dataset.id));
      swipe.dir = Math.sign(dx);
      swipe.action = swipe.dir === replyDir ? "reply" : (m && m.mine ? "info" : null);
      if (!swipe.action) { swipe = null; return; }
      swipe.hint = document.createElement("span");
      swipe.hint.className = "swipe-hint";
      swipe.hint.innerHTML = swipe.action === "reply" ? REPLY_ICON : INFO_ICON;
      swipe.hint.style[swipe.dir > 0 ? "left" : "right"] = "4px";
      swipe.el.appendChild(swipe.hint);
      swipe.bubble.style.transition = "none";
    }
    const pull = Math.min(SWIPE_MAX, Math.max(0, dx * swipe.dir) * 0.75);
    swipe.bubble.style.transform = `translateX(${pull * swipe.dir}px)`;
    swipe.hint.style.opacity = String(Math.min(1, pull / SWIPE_AT));
    swipe.hint.classList.toggle("ready", pull >= SWIPE_AT);
    if (pull >= SWIPE_AT && !swipe.ready) { swipe.ready = true; navigator.vibrate?.(8); }
    if (pull < SWIPE_AT) swipe.ready = false;
  }, { passive: true });
  const endSwipe = () => {
    if (!swipe || swipe.mode !== "h") { swipe = null; return; }
    const { bubble, hint, ready, action, el } = swipe;
    swipe = null;
    bubble.style.transition = "transform .22s cubic-bezier(.2, .8, .2, 1)";
    bubble.style.transform = "";
    setTimeout(() => { hint.remove(); bubble.style.transition = ""; }, 240);
    const m = messages.get(Number(el.dataset.id));
    if (!ready || !m) return;
    if (action === "reply") setReply(m);
    else showInfo(m);
  };
  list.addEventListener("touchend", endSwipe, { passive: true });
  list.addEventListener("touchcancel", endSwipe, { passive: true });
})();
