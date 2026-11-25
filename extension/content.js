// Console-style spatial navigation: focus box, selection, back, search, player-mode keys.
(() => {
  const CC = window.__cc;
  if (!CC || window.top !== window || CC.contentLoaded) return;
  CC.contentLoaded = true;
  const api = globalThis.browser ?? globalThis.chrome;
  const osk = CC.osk;
  const box = CC.boxEl;

  const SELECTABLE = [
    "a[href]", "button", "input:not([type=hidden])", "select", "textarea", "summary", "iframe",
    "[role=button]", "[role=link]", "[role=menuitem]", "[role=menuitemcheckbox]", "[role=menuitemradio]",
    "[role=tab]", "[role=checkbox]", "[role=switch]", "[role=option]", "[role=radio]", "[role=combobox]",
    "[contenteditable='']", "[contenteditable=true]", "[tabindex]:not([tabindex='-1'])", "[onclick]",
  ].join(",");
  const SKIP_BUTTONS = [
    ".ytp-skip-ad-button", ".ytp-ad-skip-button", ".ytp-ad-skip-button-modern",
    "[data-uia=player-skip-intro]", "[data-uia=player-skip-recap]",
    "[data-uia=next-episode-seamless-button]", "[data-uia=next-episode-seamless-button-draining]",
  ].join(",");
  const SEARCH_BOXES = [
    "input[type=search]", "input[name=search_query]", "input[name=q]", "input[name=query]",
    "input[name=search]", "[role=searchbox]", "input[role=combobox][aria-label*=earch i]",
  ].join(",");
  // Native controls where a real Enter/Space key gives the page a trusted user activation.
  const ENTER_TARGETS = "a[href],button,summary,input[type=button],input[type=submit],input[type=reset],input[type=image]";
  const SPACE_TARGETS = "input[type=checkbox],input[type=radio]";

  let cur = null;              // element with the focus box
  let pageCur = null;          // page element to return to when the OSK closes
  let controllerMode = false;  // true once the controller has driven this page
  let idle = false;            // keyboard/mouse took over: no focus box until the controller is used again
  let lastCtl = 0;             // last time the controller itself did something (message or key it asked for)
  let lastMouse = null;
  const CTL_WINDOW = 250;      // ms; the daemon's own key presses land this close to its "ctl" message
  let paused = false;          // true while the daemon is in forced mouse mode
  let lastScrollRetry = 0;
  let lastEscape = { el: null, at: 0 };

  const safe = (fn) => { try { return fn(); } catch { return undefined; } };
  const send = (msg) => safe(() => api.runtime.sendMessage(msg).catch(() => {}));
  const isVisible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
  };

  // ---- window focus + typing reporting (tells the daemon when to use browser mode) ----
  const reportFocus = () => send({
    type: "focus",
    value: document.hasFocus() && document.visibilityState === "visible",
  });
  addEventListener("focus", () => { reportFocus(); if (cur && !paused) track(); });
  addEventListener("blur", () => setTimeout(reportFocus, 0));
  addEventListener("pageshow", reportFocus);   // back/forward cache restores
  document.addEventListener("visibilitychange", () => { reportFocus(); if (cur && !paused) track(); });

  // ---- hand-off: real keyboard / mouse input hides the box until the controller is used again ----
  const markCtl = () => { lastCtl = performance.now(); };
  function takeOver() {
    controllerMode = false;
    if (idle) return;
    idle = true;
    box.style.display = "none";
    osk.setIdle(true);
  }
  function wake() {
    if (!idle) return;
    idle = false;
    osk.setIdle(false);
    if (cur && !paused) track();
  }
  // The daemon's own key presses are trusted events too; they arrive within a moment of a "ctl"
  // message (or of a key we asked for), in either order, so only input outside that window counts.
  function userInput() {
    const t = performance.now();
    if (Math.abs(t - lastCtl) < CTL_WINDOW) return;
    setTimeout(() => { if (lastCtl < t - CTL_WINDOW) takeOver(); }, CTL_WINDOW);
  }
  addEventListener("mousemove", (e) => {
    if (!e.isTrusted) return;
    // Browsers repeat the old position after a scroll or layout change; only real motion counts.
    const moved = lastMouse ? Math.hypot(e.screenX - lastMouse.x, e.screenY - lastMouse.y)
      : Math.hypot(e.movementX || 0, e.movementY || 0);
    lastMouse = { x: e.screenX, y: e.screenY };
    if (moved >= 2) takeOver();
  }, { capture: true, passive: true });
  for (const type of ["mousedown", "keydown"]) {
    addEventListener(type, (e) => { if (e.isTrusted) userInput(); }, { capture: true, passive: true });
  }
  document.addEventListener("focusin", (e) => {
    if (osk.isEditable(e.target)) send({ type: "typing", value: true });
  }, true);
  document.addEventListener("focusout", (e) => {
    if (osk.isEditable(e.target) && !osk.isEditable(e.relatedTarget)) send({ type: "typing", value: false });
  }, true);
  reportFocus();

  // ---- candidate collection ----
  const related = (a, b) => {
    for (let n = a; n; n = n.parentNode || n.host) if (n === b) return true;
    for (let n = b; n; n = n.parentNode || n.host) if (n === a) return true;
    return false;
  };

  function deepAll(root, out) {
    out.push(...root.querySelectorAll(SELECTABLE));
    for (const el of root.querySelectorAll("*")) if (el.shadowRoot) deepAll(el.shadowRoot, out);
    return out;
  }

  const tiny = (el) => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width < 6 || r.height < 6 || st.opacity === "0" || st.visibility === "hidden";
  };

  function collect() {
    const vw = innerWidth, vh = innerHeight;
    const all = deepAll(document, []);
    // Custom checkboxes/toggles hide the real control and make its <label> the click target.
    for (const l of document.querySelectorAll("label[for]")) {
      const c = document.getElementById(l.htmlFor);
      if (c && tiny(c)) all.push(l);
    }
    const out = [];
    for (const el of all) {
      if (el.disabled || el.closest("[inert],[aria-hidden=true]")) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 6 || r.height < 6) continue;
      if (el.tagName === "IFRAME" && (r.width < 200 || r.height < 120)) continue;
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
      el.dispatchEvent(new Ctor(t, {
        bubbles: !/enter|leave/.test(t), cancelable: !/enter|leave/.test(t), composed: true,
        view: window, detail: t === "click" ? 1 : 0, ...init,
      }));
    }
  }

  function place() {
    const r = cur.getBoundingClientRect();
    const pad = 3;
    box.style.transform = `translate(${r.left - pad}px, ${r.top - pad}px)`;
    box.style.width = `${r.width + pad * 2}px`;
    box.style.height = `${r.height + pad * 2}px`;
  }

  let glideTimer = 0;
  function setCursor(el) {
    if (cur && cur !== el && cur.isConnected && !osk.keys().includes(cur)) {
      fire(cur, ["pointerout", "mouseout", "mouseleave"], {});
    }
    cur = el;
    osk.mark(el);
    paused = false;
    if (!el || idle) { box.style.display = "none"; return; }
    CC.raise();
    if (osk.keys().includes(el)) {   // keyboard keys show their own selected state, no floating ring
      box.style.display = "none";
      return;
    }
    let r = el.getBoundingClientRect();
    const needsV = r.top < 90 || r.bottom > innerHeight - 60;
    if (needsV || r.left < 0 || r.right > innerWidth) {
      el.scrollIntoView({ block: needsV ? "center" : "nearest", inline: "nearest", behavior: "instant" });
      r = el.getBoundingClientRect();
    }
    fire(el, ["pointerover", "mouseover", "pointerenter", "mouseenter", "mousemove"],
      { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 });
    // Glide only between two visible targets; the first show snaps into place.
    const glide = box.style.display === "block";
    box.classList.toggle("glide", glide);
    place();
    box.style.display = "block";
    clearTimeout(glideTimer);
    if (glide) glideTimer = setTimeout(() => box.classList.remove("glide"), 160);
    track();
  }
  CC.setCursor = setCursor;

  // True when the box would be pointing at something the user can't see (faded-out player controls,
  // an element a page overlay now covers) or when the controller is steering a fullscreen video.
  function boxHidden() {
    if (document.fullscreenElement && !osk.isOpen()) return true;   // player mode: keys go to the video
    for (let n = cur, i = 0; n && n !== document.documentElement && i < 12; n = n.parentElement || n.getRootNode()?.host, i++) {
      const st = getComputedStyle(n);
      if (st.opacity === "0" || st.visibility === "hidden" || st.display === "none") return true;
    }
    const r = cur.getBoundingClientRect();
    const t = document.elementFromPoint(
      Math.min(innerWidth - 1, Math.max(0, r.left + r.width / 2)),
      Math.min(innerHeight - 1, Math.max(0, r.top + r.height / 2)));
    return !!t && !related(cur, t) && r.top >= 0 && r.bottom <= innerHeight;
  }

  let tracking = false;
  function track() {
    if (tracking) return;
    tracking = true;
    let n = 0;
    const frame = () => {
      if (!cur || !cur.isConnected || paused || idle || !document.hasFocus() || osk.keys().includes(cur)) {
        if (!osk.keys().includes(cur)) box.style.display = "none";
        tracking = false;
        return;
      }
      const r = cur.getBoundingClientRect();
      // The visibility check walks ancestors, so run it a few times a second, not every frame.
      if (n++ % 6 === 0) box.dataset.hide = boxHidden() ? "1" : "";
      if (!r.width || !r.height || box.dataset.hide) { box.style.display = "none"; }
      else { place(); box.style.display = "block"; }
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }
  document.addEventListener("fullscreenchange", () => {
    if (document.fullscreenElement) box.style.display = "none";
    else if (cur && !paused) track();
  });

  // ---- actions ----
  const playerMode = () => !!document.fullscreenElement && !osk.isOpen();

  function sendKey(key) {
    markCtl();
    // A focused text field would swallow the daemon's real key presses.
    const a = document.activeElement;
    if (key !== "slash" && a && osk.isEditable(a)) a.blur();
    send({ type: "key", key });
  }

  function lost() {
    if (!cur || !cur.isConnected) return true;
    const r = cur.getBoundingClientRect();
    return !r.width || !r.height || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth;
  }

  function nav(dir, retried = false) {
    controllerMode = true;
    if (playerMode()) return sendKey(dir);
    const typing = osk.isOpen();
    const cands = typing ? osk.keys() : collect();
    if (typing) {
      if (!cands.includes(cur)) return setCursor(cands[0]);
    } else if (lost()) {
      return setCursor(nearestToCenter(cands) ?? cands[0] ?? null);
    }
    const next = pick(cur, cands, dir);
    if (next) return setCursor(next);
    if (typing) return;
    if (!cands.includes(cur) && cands.length) return setCursor(nearestToCenter(cands));  // e.g. covered by a hover card
    if (retried || (dir !== "up" && dir !== "down")) return;
    const before = scrollY;
    scrollBy({ top: (dir === "down" ? 1 : -1) * innerHeight * 0.7 });
    if (Date.now() - lastScrollRetry > 100) {
      lastScrollRetry = Date.now();
      setTimeout(() => { if (scrollY !== before) nav(dir, true); }, 120);
    }
  }

  function cycleSelect(sel) {
    if (!sel.options.length) return;
    sel.selectedIndex = (sel.selectedIndex + 1) % sel.options.length;
    sel.dispatchEvent(new Event("input", { bubbles: true }));
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    CC.toast(sel.options[sel.selectedIndex].text);
  }

  function select() {
    controllerMode = true;
    if (playerMode()) {
      const skip = [...document.querySelectorAll(SKIP_BUTTONS)].find((b) => b.getBoundingClientRect().width > 0);
      return skip ? skip.click() : sendKey("space");
    }
    if (osk.isOpen()) return cur?.click();
    if (!cur || !cur.isConnected) return nav("down");
    if (osk.isEditable(cur)) return osk.open(cur);
    if (cur instanceof HTMLSelectElement) return cycleSelect(cur);

    // Real key presses count as a trusted user activation: popups, autoplay, fullscreen and
    // file choosers all stay allowed, and links honour target=_blank.
    const key = cur.matches(ENTER_TARGETS) ? "enter" : cur.matches(SPACE_TARGETS) ? "space"
      : cur.tagName === "IFRAME" ? "space" : null;
    if (key) {
      cur.focus({ preventScroll: true });
      if (document.activeElement === cur || cur.tagName === "IFRAME") return sendKey(key);
    }
    const r = cur.getBoundingClientRect();
    const init = { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, button: 0 };
    if (cur.matches("a,button,input,summary,label,textarea")) cur.click();
    else fire(cur, ["pointerdown", "mousedown", "pointerup", "mouseup", "click"], init);
  }

  function escape() {
    const t = document.activeElement || document.body;
    for (const type of ["keydown", "keyup"]) {
      t.dispatchEvent(new KeyboardEvent(type, { key: "Escape", code: "Escape", keyCode: 27, which: 27,
        bubbles: true, cancelable: true, composed: true }));
    }
  }

  // Dismiss an open dialog/popover/menu instead of leaving the page.
  function dismissOverlay() {
    const dlg = document.querySelector("dialog[open]");
    if (dlg) { dlg.close?.(); return true; }
    const pop = safe(() => [...document.querySelectorAll(":popover-open")].filter((e) => e !== CC.host).pop());
    if (pop) { safe(() => pop.hidePopover()); return true; }
    const overlay = [...document.querySelectorAll("[aria-modal=true],[role=menu],[role=listbox]")]
      .find((e) => isVisible(e));
    if (!overlay) return false;
    // Escape can't be verified; if the same overlay is still there on a second press, let B go back.
    if (lastEscape.el === overlay && Date.now() - lastEscape.at < 1500) return false;
    lastEscape = { el: overlay, at: Date.now() };
    escape();
    return true;
  }

  function back() {
    if (osk.isOpen()) return osk.close();
    if (document.fullscreenElement) return void document.exitFullscreen();
    const a = document.activeElement;
    if (a && osk.isEditable(a)) return a.blur();
    if (dismissOverlay()) return;
    history.back();
  }

  function findSearch() {
    return [...document.querySelectorAll(SEARCH_BOXES)].find((e) => osk.isEditable(e) && isVisible(e));
  }

  function search() {
    controllerMode = true;
    if (osk.isOpen()) return;
    let field = document.activeElement;
    if (!osk.isEditable(field)) field = findSearch();
    if (field) { setCursor(field); return osk.open(field); }
    const launcher = document.querySelector("[data-uia=search-box-launcher]");   // Netflix
    if (launcher) {
      launcher.click();
      return void setTimeout(() => { const f = findSearch(); if (f) { setCursor(f); osk.open(f); } }, 400);
    }
    sendKey("slash");   // site-specific search shortcut (YouTube, GitHub, ...)
  }

  CC.onOskOpen = () => { pageCur = cur; };
  CC.onOskClose = (target) => {
    setCursor(target && target.isConnected ? target : pageCur);
    pageCur = null;
  };

  // Anything that focuses a text field while the controller is in charge should raise the keyboard.
  document.addEventListener("focusin", (e) => {
    if (controllerMode && !osk.isOpen() && osk.isEditable(e.target)) {
      cur = e.target;
      osk.open(e.target);
    }
  }, true);

  // First controller press after keyboard/mouse use: bring the box back to where it was
  // (or the middle of the page) instead of moving or clicking on something the user can't see.
  function reveal() {
    controllerMode = true;
    const cands = osk.isOpen() ? osk.keys() : collect();
    if (osk.isOpen()) return setCursor(cands.includes(cur) ? cur : cands[0]);
    setCursor(lost() ? nearestToCenter(cands) ?? cands[0] ?? null : cur);
  }

  api.runtime.onMessage.addListener((msg) => {
    if (msg.type === "report") return reportFocus();
    markCtl();   // whatever key presses follow are the controller's, not the user's keyboard
    if (msg.type === "ctl") return;
    if (msg.type === "help") return CC.helpIsOpen() ? CC.hideHelp() : CC.showHelp(msg.bindings);
    // While the controls list is up, any button just dismisses it (sticks are ignored).
    if (CC.helpIsOpen() && !["mode", "nav"].includes(msg.type)) return CC.hideHelp();
    if (idle) {
      const blind = (msg.type === "nav" || msg.type === "select") && !playerMode();
      wake();
      if (blind) return reveal();
    }
    switch (msg.type) {
      case "nav": return nav(msg.dir);
      case "select": return select();
      case "back": return back();
      case "search": return search();
      case "osk": {
        controllerMode = true;
        const a = document.activeElement;
        if (osk.isOpen()) return osk.close();
        return osk.open(osk.isEditable(cur) ? cur : osk.isEditable(a) ? a : null);
      }
      case "mode":
        CC.toast(msg.mouse ? "Mouse mode" : "Controller navigation");
        if (msg.mouse) { paused = true; controllerMode = false; box.style.display = "none"; }
        else if (!osk.isOpen()) setCursor(lost() ? nearestToCenter(collect()) : cur);
        return;
    }
  });
})();
