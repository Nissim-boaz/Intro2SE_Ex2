// Course chat: polling every 2.5s, bubbles, reply-with-quote, reactions and polls.
(function () {
  const root = document.getElementById("chat-root");
  if (!root) return;
  const listUrl = root.dataset.listUrl;
  const sendUrl = root.dataset.sendUrl;
  const pollUrl = root.dataset.pollUrl;
  const canVote = root.dataset.canVote === "1";
  const POLL_MS = 2500;

  const scroller = document.getElementById("chat-scroll");
  const list = document.getElementById("chat-list");
  const empty = document.getElementById("chat-empty");
  const bar = document.getElementById("reaction-bar");
  const input = document.getElementById("chat-input");
  const status = document.getElementById("chat-status");
  const esc = Model.escape;

  const messages = new Map(); // id -> message
  let since = 0;
  let replyTo = null;
  let barFor = null;
  let timer = null;

  // ---------- rendering ----------
  const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });

  function renderPoll(p, mine) {
    const total = p.total || 0;
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
    const hint = canVote ? (p.my_vote ? "אפשר לשנות את הבחירה" : "בחר תשובה אחת") : "ההצבעה אנונימית";
    return `<div class="poll">
        <div class="poll-q">${esc(p.question)}</div>
        <div class="poll-hint">${hint}</div>
        <div class="poll-opts">${rows}</div>
        <div class="poll-total">${total === 1 ? "הצבעה אחת" : total + " הצבעות"}</div>
      </div>`;
  }

  function renderMessage(m) {
    const quote = m.reply_to
      ? `<button type="button" class="quote" data-jump="${m.reply_to.id}"><strong>${esc(m.reply_to.sender_name)}</strong><span>${esc(m.reply_to.body)}</span></button>`
      : "";
    const who = m.mine
      ? (m.anonymous ? `<div class="who who-anon">נשלח כאנונימי</div>` : "")
      : `<div class="who${m.anonymous ? " who-anon" : ""}">${esc(m.sender_name)}${m.sender_is_lecturer ? ' <span class="who-badge">מרצה</span>' : ""}</div>`;
    const body = m.poll ? renderPoll(m.poll, m.mine) : `<div class="text" dir="auto">${esc(m.body)}</div>`;
    const r = m.reactions;
    const summary = r.summary.length
      ? `<button type="button" class="reactions" data-who="${m.id}" aria-label="מי הגיב">${r.summary.map(([e, n]) => `<span>${e}${n > 1 ? ` ${n}` : ""}</span>`).join("")}</button>`
      : "";
    return `<div class="msg ${m.mine ? "mine" : "theirs"}${m.poll ? " has-poll" : ""}" id="msg-${m.id}" data-id="${m.id}">
        <div class="bubble" tabindex="0">
          ${who}${quote}${body}
          <span class="time">${fmtTime(m.created_at)}</span>
          <button type="button" class="msg-more" data-more="${m.id}" aria-label="תגובה או השב">☺</button>
        </div>
        ${summary}
      </div>`;
  }

  function upsert(m) {
    messages.set(m.id, m);
    const html = renderMessage(m);
    const existing = document.getElementById("msg-" + m.id);
    if (existing) {
      existing.outerHTML = html;
    } else {
      list.insertAdjacentHTML("beforeend", html);
    }
  }

  function nearBottom() {
    return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
  }

  function scrollToBottom(smooth) {
    scroller.scrollTo({ top: scroller.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }

  // ---------- polling ----------
  async function refresh(first) {
    clearTimeout(timer);
    try {
      const stick = first || nearBottom();
      const d = await Model.api(listUrl + (since ? `?since=${since}` : ""));
      since = d.now;
      let added = false;
      d.messages.forEach((m) => {
        if (!messages.has(m.id)) added = true;
        upsert(m);
      });
      empty.hidden = messages.size > 0;
      if (added && stick) scrollToBottom(!first);
      status.textContent = "";
    } catch (err) {
      status.textContent = err.status === 401 ? "צריך להתחבר מחדש" : "אין חיבור. מנסה שוב";
    }
    if (!document.hidden) timer = setTimeout(refresh, POLL_MS);
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
    else clearTimeout(timer);
  });

  // ---------- composer ----------
  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(140, input.scrollHeight) + "px";
  }
  input.addEventListener("input", autosize);
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
    const btn = document.getElementById("chat-send");
    btn.disabled = true;
    try {
      await Model.api(sendUrl, { json: { body: text, reply_to: replyTo, anonymous: !!(anon && anon.checked) } });
      input.value = "";
      autosize();
      setReply(null);
      await refresh();
      scrollToBottom(true);
    } catch (err) {
      Model.toast(err.message, "error");
    } finally {
      btn.disabled = false;
      input.focus();
    }
  });

  // ---------- reaction bar: long-press on touch, hover/button on desktop ----------
  function openBar(msgEl) {
    barFor = Number(msgEl.dataset.id);
    const m = messages.get(barFor);
    bar.querySelectorAll("[data-emoji]").forEach((b) => b.classList.toggle("active", m && m.reactions.mine === b.dataset.emoji));
    bar.hidden = false;
    const bubble = msgEl.querySelector(".bubble").getBoundingClientRect();
    const host = root.getBoundingClientRect();
    const top = Math.max(4, bubble.top - host.top - bar.offsetHeight - 8);
    bar.style.top = top + "px";
    const isMine = msgEl.classList.contains("mine");
    bar.style.left = isMine ? "12px" : "auto";
    bar.style.right = isMine ? "auto" : "12px";
    navigator.vibrate?.(10);
  }
  function closeBar() { bar.hidden = true; barFor = null; }

  let pressTimer = null;
  let pressed = false;
  list.addEventListener("touchstart", (e) => {
    const msgEl = e.target.closest(".msg");
    if (!msgEl || e.target.closest("button")) return;
    pressed = false;
    pressTimer = setTimeout(() => { pressed = true; openBar(msgEl); }, 450);
  }, { passive: true });
  ["touchend", "touchmove", "touchcancel"].forEach((ev) =>
    list.addEventListener(ev, () => clearTimeout(pressTimer), { passive: true }));
  list.addEventListener("contextmenu", (e) => {
    const msgEl = e.target.closest(".msg");
    if (msgEl) { e.preventDefault(); openBar(msgEl); }
  });

  // desktop: hovering a bubble opens the bar after a short pause, leaving closes it
  if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    let hoverTimer = null;
    let leaveTimer = null;
    list.addEventListener("mouseover", (e) => {
      const msgEl = e.target.closest(".msg");
      if (!msgEl) return;
      clearTimeout(leaveTimer);
      if (barFor === Number(msgEl.dataset.id)) return;
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(() => openBar(msgEl), 350);
    });
    const leave = () => {
      clearTimeout(hoverTimer);
      leaveTimer = setTimeout(closeBar, 350);
    };
    list.addEventListener("mouseleave", leave);
    list.addEventListener("mouseout", (e) => {
      if (!e.relatedTarget || !e.relatedTarget.closest(".msg")) leave();
    });
    bar.addEventListener("mouseenter", () => clearTimeout(leaveTimer));
    bar.addEventListener("mouseleave", leave);
  }

  bar.addEventListener("click", async (e) => {
    const btn = e.target.closest("button");
    if (!btn || barFor === null) return;
    const id = barFor;
    closeBar();
    if (btn.dataset.action === "reply") return setReply(messages.get(id));
    try {
      await Model.api(`/api/messages/${id}/reactions`, { json: { emoji: btn.dataset.emoji } });
      refresh();
    } catch (err) { Model.toast(err.message, "error"); }
  });

  document.addEventListener("click", (e) => {
    if (!bar.hidden && !bar.contains(e.target) && !e.target.closest("[data-more]") && !pressed) closeBar();
    pressed = false;
  });
  scroller.addEventListener("scroll", closeBar, { passive: true });

  list.addEventListener("click", async (e) => {
    const more = e.target.closest("[data-more]");
    if (more) return openBar(more.closest(".msg"));

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
      try {
        const d = await Model.api(`/api/messages/${who.dataset.who}/reactions`);
        document.getElementById("who-list").innerHTML = d.reactions
          .map((r) => `<li><span style="font-size:22px">${r.emoji}</span><span class="grow">${esc(r.name)}</span></li>`).join("");
        document.getElementById("who-dialog").showModal();
      } catch (err) { Model.toast(err.message, "error"); }
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
    function reset() {
      box.querySelectorAll("input").forEach((i) => i.remove());
      addRow(); addRow();
      document.getElementById("poll-question").value = "";
    }
    box.addEventListener("input", () => {
      const inputs = [...box.querySelectorAll("input")];
      if (inputs[inputs.length - 1].value.trim()) addRow();
    });
    pollForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const options = [...box.querySelectorAll("input")].map((i) => i.value.trim()).filter(Boolean);
      try {
        await Model.api(pollUrl, { json: { question: document.getElementById("poll-question").value, options } });
        document.getElementById("poll-dialog").close();
        reset();
        await refresh();
        scrollToBottom(true);
      } catch (err) { Model.toast(err.message, "error"); }
    });
    reset();
  }

  refresh(true);
})();
