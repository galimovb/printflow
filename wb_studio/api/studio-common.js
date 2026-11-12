/* Shared by the studio pages: sign-in (session cookie), tabs, API calls, messages, loaders, status chips. */
const WB = (() => {
  const TABS = [["/studio/wb/themes", "Темы"], ["/studio/wb/queue", "Очередь"], ["/studio/wb/review", "Проверка перед WB"]];
  let onReady = null;
  let msg = null;

  function node(tag, text, cls) {
    const n = document.createElement(tag);
    if (text !== undefined && text !== null) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  }

  /** One way to tell the user what happened: the message area in the header. kind: "" | "ok" | "error". */
  function say(text, kind = "") {
    if (!msg) return;
    msg.textContent = text || "";
    msg.className = "wb-msg " + kind;
  }

  /** Spinner on the button while the work runs; errors go to the message area. */
  async function busy(button, work) {
    const label = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="spin"></span>' + label;
    try { return await work(); }
    catch (e) { say(e.message, "error"); }
    finally { button.innerHTML = label; button.disabled = false; }
  }

  function when(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleString("ru", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  function ago(iso) {
    if (!iso) return "";
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return Math.round(s) + " с назад";
    if (s < 3600) return Math.round(s / 60) + " мин назад";
    if (s < 86400) return Math.round(s / 3600) + " ч назад";
    return when(iso);
  }

  /** Status chip; kind is one of accent, ok, warn, bad, info or empty for neutral. */
  function chip(text, kind = "") { return node("span", text, "chip " + kind); }

  /** Table body placeholder rows while loading. */
  function skeletonRows(tbody, widths, rows = 6) {
    tbody.replaceChildren();
    for (let i = 0; i < rows; i++) {
      const tr = node("tr");
      for (const w of widths) { const td = node("td"); const s = node("div", undefined, "sk"); s.style.width = w + "px"; td.append(s); tr.append(td); }
      tbody.append(tr);
    }
  }

  /** Table body with one "nothing here" row. */
  function emptyRow(tbody, text, columns) {
    const tr = node("tr"); const td = node("td", text, "empty"); td.colSpan = columns; tr.append(td); tbody.replaceChildren(tr);
  }

  function photo(url, label, cls) {
    const w = node("div", undefined, "ph " + (cls || ""));
    const a = node("a"); a.href = url; a.target = "_blank"; a.rel = "noopener";
    const i = node("img"); i.loading = "lazy"; i.src = url; a.append(i); w.append(a);
    if (label) w.append(node("div", label, "lab"));
    return w;
  }

  function login() {
    if (document.querySelector(".wb-veil")) return;
    const veil = node("div", undefined, "wb-veil");
    const box = node("form", undefined, "wb-login");
    const input = node("input");
    input.type = "password"; input.placeholder = "PRINTFLOW_WB_API_TOKEN"; input.autocomplete = "off";
    const error = node("div", "", "error");
    const button = node("button", "Войти");
    box.append(node("h2", "Вход в WB Studio"),
      node("p", "Токен из .env (PRINTFLOW_WB_API_TOKEN) вводится один раз: браузер запомнит вход на 30 дней."),
      input, error, button);
    box.onsubmit = async (e) => {
      e.preventDefault();
      button.disabled = true;
      try {
        const r = await fetch("/api/v1/wb-studio/session", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: input.value.trim() }), credentials: "same-origin" });
        if (!r.ok) { error.textContent = "Неверный токен"; return; }
        veil.remove();
        if (onReady) onReady();
      } finally { button.disabled = false; }
    };
    veil.append(box);
    document.body.append(veil);
    input.focus();
  }

  async function api(path, body) {
    const r = await fetch("/api/v1/wb-studio" + path, {
      method: body ? "POST" : "GET", headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined, credentials: "same-origin",
    });
    if (r.status === 401) { login(); throw Error("Нужно войти"); }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data));
    return data;
  }

  function header() {
    const place = document.querySelector("header");
    const nav = node("nav", undefined, "wb-nav");
    for (const [href, label] of TABS) {
      const a = node("a", label, location.pathname === href ? "on" : "");
      a.href = href; nav.append(a);
    }
    const live = node("div", undefined, "wb-live");
    msg = node("span", "", "wb-msg");
    const out = node("button", "Выйти", "wb-out");
    out.onclick = async () => { await fetch("/api/v1/wb-studio/session/end", { method: "POST", credentials: "same-origin" }); location.reload(); };
    live.append(msg, out);
    place.replaceChildren(nav, live);
  }

  function start(ready) {
    header();
    onReady = ready;
    ready();
  }

  return { api, node, say, busy, when, ago, chip, skeletonRows, emptyRow, photo, start, login };
})();
