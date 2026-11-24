// Console-style spatial navigation: focus box, selection, back, player-mode keys.
(() => {
  const CC = window.__cc;
  if (!CC || window.top !== window) return;
  const api = globalThis.browser ?? globalThis.chrome;
  const osk = CC.osk;
  const box = CC.boxEl;

  const SELECTABLE = [
    "a[href]", "button", "input:not([type=hidden])", "select", "textarea", "summary",
    "[role=button]", "[role=link]", "[role=menuitem]", "[role=tab]", "[role=checkbox]",
    "[role=switch]", "[role=option]", "[role=radio]", "[role=combobox]",
    "[contenteditable='']", "[contenteditable=true]", "[tabindex]:not([tabindex='-1'])", "[onclick]",
  ].join(",");
  const SKIP_BUTTONS = [
    ".ytp-skip-ad-button", ".ytp-ad-skip-button", ".ytp-ad-skip-button-modern",
    "[data-uia=player-skip-intro]", "[data-uia=player-skip-recap]",
    "[data-uia=next-episode-seamless-button]", "[data-uia=next-episode-seamless-button-draining]",
  ].join(",");

  let cur = null;              // element with the focus box
  let pageCur = null;          // page element to return to when the OSK closes
  let controllerMode = false;  // true once the controller has driven this page
  let lastScrollRetry = 0;

  // ---- window focus reporting (tells the daemon when to use browser mode) ----
  const reportFocus = () => {
    try {
      api.runtime.sendMessage({
        type: "focus",
        value: document.hasFocus() && document.visibilityState === "visible",
      }).catch(() => {});
    } catch {}
  };
  addEventListener("focus", reportFocus);
  addEventListener("blur", () => setTimeout(reportFocus, 0));
  document.addEventListener("visibilitychange", reportFocus);
  addEventListener("mousemove", (e) => { if (e.isTrusted) controllerMode = false; }, true);
  reportFocus();

  // ---- candidate collection ----
  const related = (a, b) => {
    for (let n = a; n; n = n.parentNode || n.host) if (n === b) return true;
    for (let n = b; n; n = n.parentNode || n.host) if (n === a) return true;
    return false;
  };

  function collect() {
    const vw = innerWidth, vh = innerHeight;
    const out = [];
    for (const el of document.querySelectorAll(SELECTABLE)) {
      if (el.disabled || el.closest("[inert],[aria-hidden=true]") || el.type === "hidden") continue;
      const r = el.getBoundingClientRect();
      if (r.width < 6 || r.height < 6) continue;
      if (r.bottom < -vh * 0.3 || r.top > vh * 1.3 || r.right < -vw * 0.3 || r.left > vw * 1.3) continue;
      const st = getComputedStyle(el);
      if (st.visibility === "hidden" || st.pointerEvents === "none" || st.opacity === "0") continue;
      if (r.top >= 0 && r.left >= 0 && r.bottom <= vh && r.right <= vw) {
        const t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        if (t && !related(el, t)) continue;   // covered by a dialog/overlay
      }
      out.push(el);
    }
    // Drop wrapper elements that merely hug a smaller selectable child.
    const set = new Set(out), drop = new Set();
    const area = (e) => { const r = e.getBoundingClientRect(); return r.width * r.height; };
    for (const el of out) {
      for (let p = el.parentElement; p; p = p.parentElement) {
        if (set.has(p) && area(p) < area(el) * 1.5) drop.add(p);
      }
    }
    return out.filter((e) => !drop.has(e));
  }

  // ---- direction scoring ----
  const gap = (a1, a2, b1, b2) => Math.max(0, Math.max(a1, b1) - Math.min(a2, b2));

  function pick(from, cands, dir) {
    const a = from.getBoundingClientRect();
    const ax = a.left + a.width / 2, ay = a.top + a.height / 2;
    let best = null, bestScore = Infinity;
    for (const c of cands) {
      if (c === from) continue;
      const r = c.getBoundingClientRect();
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      let main, perp, off, along;
      if (dir === "right" || dir === "left") {
        const ahead = dir === "right" ? cx - ax : ax - cx;
        if (ahead <= 1) continue;
        main = dir === "right" ? Math.max(0, r.left - a.right) : Math.max(0, a.left - r.right);
        perp = gap(a.top, a.bottom, r.top, r.bottom);
        off = Math.abs(cy - ay); along = ahead;
      } else {
        const ahead = dir === "down" ? cy - ay : ay - cy;
        if (ahead <= 1) continue;
        main = dir === "down" ? Math.max(0, r.top - a.bottom) : Math.max(0, a.top - r.bottom);
        perp = gap(a.left, a.right, r.left, r.right);
        off = Math.abs(cx - ax); along = ahead;
      }
      const score = main + perp * 2.5 + off * 0.25 + along * 0.05;
      if (score < bestScore) { bestScore = score; best = c; }
    }
    return best;
  }

  function nearestToCenter(cands) {
    const cx = innerWidth / 2, cy = innerHeight * 0.4;
    let best = null, bd = Infinity;
    for (const c of cands) {
      const r = c.getBoundingClientRect();
      if (r.bottom < 0 || r.top > innerHeight) continue;
      const d = Math.hypot(r.left + r.width / 2 - cx, r.top + r.height / 2 - cy);
      if (d < bd) { bd = d; best = c; }
    }
    return best;
  }

  // ---- focus box ----
  function fire(el, types, init) {
    for (const t of types) {
      const Ctor = t.startsWith("pointer") ? PointerEvent : MouseEvent;
      el.dispatchEvent(new Ctor(t, { bubbles: !/enter|leave/.test(t), composed: true, ...init }));
    }
  }

  function setCursor(el) {
    if (cur && cur !== el && cur.isConnected && !osk.isOpen()) {
      fire(cur, ["pointerout", "mouseout", "mouseleave"], {});
    }
    cur = el;
    if (!el) { box.style.display = "none"; return; }
    const r = el.getBoundingClientRect();
    if (!osk.isOpen() || osk.keys().includes(el)) {
      const needsScroll = r.top < 90 || r.bottom > innerHeight - 60 || r.left < 0 || r.right > innerWidth;
      if (needsScroll && !osk.keys().includes(el)) el.scrollIntoView({ block: "center", inline: "nearest" });
    }
    if (!osk.keys().includes(el)) {
      const x = r.left + r.width / 2, y = r.top + r.height / 2;
      fire(el, ["pointerover", "mouseover", "pointerenter", "mouseenter", "mousemove"], { clientX: x, clientY: y });
    }
    box.style.display = "block";
    track();
  }
  CC.setCursor = setCursor;

  let tracking = false;
  function track() {
    if (tracking) return;
    tracking = true;
    const frame = () => {
      if (!cur || !cur.isConnected || !document.hasFocus()) {
        box.style.display = "none"; tracking = false; return;
      }
      const r = cur.getBoundingClientRect();
      const pad = 3;
      box.style.display = "block";
      box.style.transform = `translate(${r.left - pad}px, ${r.top - pad}px)`;
      box.style.width = `${r.width + pad * 2}px`;
      box.style.height = `${r.height + pad * 2}px`;
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }

  // ---- actions ----
  const playerMode = () => !!document.fullscreenElement && !osk.isOpen();
  const sendKey = (key) => { try { api.runtime.sendMessage({ type: "key", key }).catch(() => {}); } catch {} };

  function nav(dir, retried = false) {
    controllerMode = true;
    if (playerMode()) return sendKey(dir);
    const cands = osk.isOpen() ? osk.keys() : collect();
    if (!cur || !cur.isConnected || (!osk.isOpen() && !cands.includes(cur) && !document.contains(cur))) {
      return setCursor(nearestToCenter(cands) ?? cands[0] ?? null);
    }
    const next = pick(cur, cands, dir);
    if (next) return setCursor(next);
    if (osk.isOpen() || retried || (dir !== "up" && dir !== "down")) return;
    const before = scrollY;
    scrollBy({ top: (dir === "down" ? 1 : -1) * innerHeight * 0.7 });
    if (Date.now() - lastScrollRetry > 100) {
      lastScrollRetry = Date.now();
      setTimeout(() => { if (scrollY !== before) nav(dir, true); }, 120);
    }
  }

  function select() {
    controllerMode = true;
    if (playerMode()) {
      const skip = [...document.querySelectorAll(SKIP_BUTTONS)].find((b) => b.getBoundingClientRect().width > 0);
      return skip ? skip.click() : sendKey("space");
    }
    if (!cur || !cur.isConnected) return nav("down");
    if (osk.isOpen()) return cur.click();
    if (osk.isEditable(cur)) { osk.open(cur); return; }
    const r = cur.getBoundingClientRect();
    const init = { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, button: 0 };
    if (cur.matches("a,button,input,select,summary,label,textarea")) {
      cur.click();
    } else {
      fire(cur, ["pointerdown", "mousedown", "pointerup", "mouseup", "click"], init);
    }
  }

  function back() {
    if (osk.isOpen()) return osk.close();
    if (document.fullscreenElement) return void document.exitFullscreen();
    const a = document.activeElement;
    if (a && osk.isEditable(a)) return a.blur();
    history.back();
  }

  CC.onOskOpen = () => { pageCur = cur; };
  CC.onOskClose = (target) => {
    setCursor(target && target.isConnected ? target : pageCur);
    pageCur = null;
  };

  // YouTube's "/" (search) and other focus changes made by the controller should raise the keyboard.
  document.addEventListener("focusin", (e) => {
    if (controllerMode && !osk.isOpen() && osk.isEditable(e.target)) {
      cur = e.target;
      osk.open(e.target);
    }
  }, true);

  api.runtime.onMessage.addListener((msg) => {
    switch (msg.type) {
      case "nav": return nav(msg.dir);
      case "select": return select();
      case "back": return back();
      case "osk": {
        controllerMode = true;
        const a = document.activeElement;
        if (osk.isOpen()) return osk.close();
        return osk.open(osk.isEditable(cur) ? cur : osk.isEditable(a) ? a : null);
      }
      case "report": return reportFocus();
    }
  });
})();
