// Course page: the chat slides in over the page instead of loading a new one.
// The chat page loads quietly in a hidden frame a moment after the course page, so opening it is instant.
// The address bar shows the chat's own address, so a reload or a shared link still opens the chat,
// and the phone's back button slides it away again.
(function () {
  const link = document.querySelector("a[data-chat-open]");
  if (!link) return;
  const chatUrl = link.getAttribute("href");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let sheet = null, frame = null, ready = false, open = false, pendingHash = "";

  function build() {
    if (sheet) return;
    sheet = document.createElement("div");
    sheet.className = "chat-sheet";
    sheet.setAttribute("aria-hidden", "true");
    sheet.innerHTML = `<iframe title="צ׳אט הקורס" src="${chatUrl}?embed=1"></iframe>`;
    document.body.appendChild(sheet);
    frame = sheet.querySelector("iframe");
  }
  const post = (type) => { if (ready && frame.contentWindow) frame.contentWindow.postMessage({ type }, location.origin); };

  function show(push) {
    build();
    if (open) return;
    open = true;
    if (push) history.pushState({ chatSheet: true }, "", chatUrl);
    document.documentElement.classList.add("chat-sheet-open");
    sheet.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => sheet.classList.add("open"));
    post("chat:open");
    setTimeout(() => frame.focus(), reduce ? 0 : 320);
  }
  function hide() {
    if (!open) return;
    open = false;
    sheet.classList.remove("open");
    document.documentElement.classList.remove("chat-sheet-open");
    sheet.setAttribute("aria-hidden", "true");
    post("chat:hide");
    refreshBadge();
    // no focus on the icon here: on a phone the focus ring stayed on it, and it looked lit up
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
  }
  // leaving the chat: undo the address we pushed when there is one, so "back" and "חזרה" do the same thing
  function leave() {
    if (history.state && history.state.chatSheet) history.back();
    else hide();
  }

  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-chat-open]");
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return; // a new tab still works as usual
    e.preventDefault();
    show(true);
  });
  window.addEventListener("popstate", (e) => {
    if (e.state && e.state.chatSheet) show(false);
    else hide();
    if (pendingHash) { location.hash = pendingHash; pendingHash = ""; }
  });
  window.addEventListener("message", (e) => {
    if (e.origin !== location.origin || !frame || e.source !== frame.contentWindow) return;
    const { type, hash } = e.data || {};
    if (type === "chat:ready") { ready = true; if (open) post("chat:open"); }
    else if (type === "chat:close") leave();
    else if (type === "chat:tab") { pendingHash = hash || ""; leave(); }
  });

  async function refreshBadge() {
    try {
      const d = await Model.api(link.dataset.unreadUrl);
      let badge = link.querySelector(".tab-badge");
      if (!d.unread) { if (badge) badge.remove(); link.removeAttribute("aria-label"); return; }
      if (!badge) { badge = document.createElement("b"); badge.className = "tab-badge"; badge.setAttribute("aria-hidden", "true"); link.prepend(badge); }
      badge.textContent = d.unread > 99 ? "99+" : String(d.unread);
      link.setAttribute("aria-label", `צ׳אט, ${d.unread} הודעות שלא נקראו`);
    } catch (_) {}
  }

  // load the chat in the background once the course page has settled, or right away on the first touch
  link.addEventListener("pointerdown", build, { once: true });
  window.addEventListener("load", () => setTimeout(build, 700));
})();
