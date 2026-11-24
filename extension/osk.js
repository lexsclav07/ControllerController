// On-screen keyboard + the shadow-DOM overlay (focus box, toast) shared with content.js.
(() => {
  if (window.top !== window || window.__cc) return;
  const CC = (window.__cc = {});

  const host = document.createElement("div");
  host.id = "__controllercontroller";
  host.popover = "manual"; // top layer: stays above <dialog>.showModal() and other popovers
  host.style.cssText = "all:initial;position:fixed;inset:0;pointer-events:none;z-index:2147483647;";
  const root = host.attachShadow({ mode: "closed" });
  root.innerHTML = `<style>
    /* libadwaita look. Dark by default; light follows the browser, which follows GNOME's colour scheme.
       AccentColor is the desktop accent in Firefox; other browsers fall back to Adwaita blue. */
    .ui{
      color-scheme:light dark;
      --font:"Adwaita Sans",Cantarell,system-ui,sans-serif;
      --ease:cubic-bezier(.25,.46,.45,.94);
      --kh:min(clamp(46px,6.6vh,76px),9vh);   /* key height follows the window, not page zoom */
      --gap:calc(var(--kh) * .14);
      --bg:#222226; --fg:#fff; --edge:rgb(255 255 255/.08); --shade:rgb(0 0 6/.45);
      --accent-bg:#3584e4; --accent-fg:#fff;
    }
    @supports (color:AccentColor){.ui{--accent-bg:AccentColor;--accent-fg:AccentColorText}}
    @media (prefers-color-scheme:light){
      .ui{--bg:#fafafb;--fg:rgb(0 0 6/.8);--edge:rgb(0 0 6/.1);--shade:rgb(0 0 6/.2)}
    }
    .osk{position:fixed;left:0;right:0;bottom:0;display:none;pointer-events:none;box-sizing:border-box;
      padding:calc(var(--gap) * 1.6) max(16px,calc((100% - var(--kh) * 17) / 2)) calc(var(--gap) * 2);
      background:var(--bg);color:var(--fg);border-top:1px solid var(--edge);box-shadow:0 -8px 32px var(--shade);
      font:700 calc(var(--kh) * .42)/1 var(--font);font-synthesis:none}
    .osk.open{display:flex;flex-direction:column;gap:var(--gap);animation:cc-rise .2s var(--ease)}
    @keyframes cc-rise{from{transform:translateY(14%);opacity:0}}
    .row{display:flex;gap:var(--gap)}
    .key{flex:1 1 0;min-width:0;height:var(--kh);border-radius:calc(var(--kh) * .22);
      background:color-mix(in srgb,currentColor 10%,transparent);
      display:flex;align-items:center;justify-content:center;user-select:none;
      transition:transform .1s var(--ease)}
    .key.t{font-size:.74em}
    .key.on{background:color-mix(in srgb,var(--accent-bg) 35%,transparent)}   /* shift latched */
    .key.sel{background:var(--accent-bg);color:var(--accent-fg)}              /* controller selection */
    .key.hit{transform:scale(.93)}
    .ic{width:1.2em;height:1.2em;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
    .ic.f{fill:currentColor}
    /* Focus ring: accent + white keyline so it reads on white, black and photographic pages. */
    .box{position:fixed;left:0;top:0;width:0;height:0;display:none;box-sizing:border-box;
      border:3px solid var(--accent-bg);border-radius:12px;
      box-shadow:0 0 0 2px rgb(255 255 255/.92),0 6px 20px rgb(0 0 0/.35)}
    .box.glide{transition:transform .12s var(--ease),width .12s var(--ease),height .12s var(--ease)}
    .toast{position:fixed;left:50%;bottom:5vh;transform:translateX(-50%);padding:.65em 1.3em;border-radius:99px;
      background:rgb(0 0 0/.65);color:rgb(255 255 255/.92);font:700 20px/1 var(--font);opacity:0;
      transition:opacity .2s var(--ease)}
    .toast.show{opacity:1}
    .help{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);display:none;box-sizing:border-box;
      width:min(760px,92vw);max-height:88vh;overflow:hidden;padding:calc(var(--kh) * .5) calc(var(--kh) * .6);
      background:var(--bg);color:var(--fg);border:1px solid var(--edge);border-radius:18px;
      box-shadow:0 12px 48px var(--shade);font:500 calc(var(--kh) * .36)/1.2 var(--font)}
    .help.open{display:block;animation:cc-pop .2s var(--ease)}
    @keyframes cc-pop{from{opacity:0;transform:translate(-50%,-48%) scale(.97)}}
    .help h2{margin:0 0 .7em;font:800 1.25em/1 var(--font)}
    .help .grid{display:grid;grid-template-columns:1fr 1fr;gap:.55em 2em}
    .help .row2{display:flex;align-items:center;gap:.7em;min-width:0}
    .help .chip{flex:none;min-width:3.4em;padding:.35em .6em;border-radius:.55em;text-align:center;font-weight:700;
      background:color-mix(in srgb,currentColor 10%,transparent)}
    .help .hint{margin:1em 0 0;opacity:.65;font-size:.85em}
    @media (prefers-reduced-motion:reduce){.ui *{animation:none!important;transition:none!important}}
  </style><div class="ui"><div class="osk"></div><div class="box"></div><div class="toast"></div><div class="help"></div></div>`;
  CC.host = host;
  CC.root = root;
  CC.boxEl = root.querySelector(".box");
  const oskEl = root.querySelector(".osk");
  const toastEl = root.querySelector(".toast");
  const helpEl = root.querySelector(".help");
  document.documentElement.appendChild(host);
  try { host.showPopover(); } catch {}

  // Re-promote above anything the page put in the top layer after us (e.g. a modal dialog).
  CC.raise = () => {
    try {
      const shown = host.matches(":popover-open");
      if (shown && !document.fullscreenElement &&
          !document.querySelector("dialog[open],[popover]:popover-open:not(#__controllercontroller)")) return;
      if (shown) host.hidePopover();
      host.showPopover();
    } catch {}
  };

  let toastTimer = 0;
  CC.toast = (text) => {
    toastEl.textContent = text;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), 1600);
  };

  // ---- controls cheat sheet (built from the daemon's live bindings) ----
  const ORDER = ["A", "B", "X", "Y", "LB", "RB", "LT", "RT", "START", "SELECT", "GUIDE", "L3", "R3",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"];
  const BUTTON_LABEL = { START: "Menu", SELECT: "View", GUIDE: "Xbox", L3: "Left stick click",
    R3: "Right stick click", DPAD_UP: "D-pad up", DPAD_DOWN: "D-pad down", DPAD_LEFT: "D-pad left",
    DPAD_RIGHT: "D-pad right" };
  const ACTION_LABEL = { select: "Select", context: "Right-click", back: "Back / close", up: "Up", down: "Down",
    left: "Left", right: "Right", seek_back: "Back 10 seconds", seek_fwd: "Forward 10 seconds",
    vol_up: "Volume up", vol_down: "Volume down", play_pause: "Play / pause", fullscreen: "Fullscreen",
    search: "Search", osk: "Keyboard", help: "This list", toggle_mode: "Mouse mode on / off",
    tab_prev: "Previous tab", tab_next: "Next tab" };
  const DIRS = new Set(["up", "down", "left", "right"]);

  CC.helpIsOpen = () => helpEl.classList.contains("open");
  CC.hideHelp = () => helpEl.classList.remove("open");
  CC.showHelp = (bindings = {}) => {
    CC.raise();
    const rows = [["Left stick / D-pad", "Move"], ["Right stick", "Scroll"]];
    for (const b of ORDER) {
      const a = bindings[b];
      if (!a || a === "none" || (b.startsWith("DPAD_") && DIRS.has(a))) continue;
      rows.push([BUTTON_LABEL[b] ?? b, ACTION_LABEL[a] ?? String(a)]);
    }
    helpEl.textContent = "";
    const title = document.createElement("h2");
    title.textContent = "Controls";
    const grid = document.createElement("div");
    grid.className = "grid";
    for (const [chip, label] of rows) {
      const row = document.createElement("div");
      row.className = "row2";
      const c = document.createElement("span");
      c.className = "chip";
      c.textContent = chip;
      const t = document.createElement("span");
      t.textContent = label;
      row.append(c, t);
      grid.appendChild(row);
    }
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = "Press any button to close";
    helpEl.append(title, grid, hint);
    helpEl.classList.add("open");
  };

  const BOTTOM = ["sym", "@", ",", "space", ".", "-", "left", "right", "enter", "close"];
  const L = {
    lower: ["1234567890", "qwertyuiop", "asdfghjkl'", ["shift", ..."zxcvbnm", "bksp"], BOTTOM],
    upper: ["1234567890", "QWERTYUIOP", 'ASDFGHJKL"', ["shift", ..."ZXCVBNM", "bksp"], BOTTOM],
    sym: ["!@#$%^&*()", "_=+[]{}<>€", ["`", "'", '"', "~", "\\", "|", "/", ":", ";", "?", "bksp"],
      ["abc", ...BOTTOM.slice(1)]],
  };

  const TEXT_KEYS = new Set(["sym", "abc", "space"]);
  const LABEL = { sym: "?123", abc: "ABC", space: "space" };
  const ICON = {
    shift: '<path d="M12 4 4 12.5h4.5V19h7v-6.5H20z"/>',
    bksp: '<path d="M9 5h10.5A1.5 1.5 0 0 1 21 6.5v11a1.5 1.5 0 0 1-1.5 1.5H9l-6-7z"/><path d="m12.5 9.5 5 5m0-5-5 5"/>',
    left: '<path d="m14.5 6-6 6 6 6"/>',
    right: '<path d="m9.5 6 6 6-6 6"/>',
    enter: '<path d="M19 6v5.5a2 2 0 0 1-2 2H5.5m0 0 4-4m-4 4 4 4"/>',
    close: '<path d="m6.5 6.5 11 11m0-11-11 11"/>',
  };
  const GROW = { shift: 1.5, bksp: 1.5, sym: 1.5, abc: 1.5, enter: 1.5, space: 3 };

  let target = null, layer = "lower", open = false;
  let lastPos = { r: 2, c: 4, last: false };   // where the controller cursor sits, kept across re-renders

  const isEditable = (el) => {
    if (!el || el.nodeType !== 1) return false;
    if (el.isContentEditable) return true;
    if (el instanceof HTMLTextAreaElement) return !el.readOnly && !el.disabled;
    if (el instanceof HTMLInputElement) {
      return !el.readOnly && !el.disabled &&
        ["text", "search", "email", "url", "password", "tel", "number", ""].includes(el.type);
    }
    return false;
  };

  function insert(text) {
    target.focus({ preventScroll: true });
    if (document.execCommand("insertText", false, text)) return;
    try {
      target.setRangeText(text, target.selectionStart, target.selectionEnd, "end");
      target.dispatchEvent(new InputEvent("input", { bubbles: true, data: text, inputType: "insertText" }));
    } catch {}
  }

  function moveCaret(delta) {
    const el = target;
    try {
      if (el.isContentEditable) {
        getSelection().modify("move", delta < 0 ? "backward" : "forward", "character");
      } else if (el.selectionStart == null) {
        // email/number inputs refuse selection APIs; borrow type=text for a moment.
        const type = el.type, len = el.value.length;
        el.type = "text";
        const p = Math.min(len, Math.max(0, (el.selectionStart ?? len) + delta));
        el.setSelectionRange(p, p);
        el.type = type;
      } else {
        const p = Math.max(0, el.selectionStart + delta);
        el.setSelectionRange(p, p);
      }
    } catch {}
  }

  function press(id) {
    if (!target || !target.isConnected) return close();
    switch (id) {
      case "shift": layer = layer === "lower" ? "upper" : "lower"; return render();
      case "sym": layer = "sym"; return render();
      case "abc": layer = "lower"; return render();
      case "close": return close();
      case "space": insert(" "); break;
      case "bksp": target.focus({ preventScroll: true }); document.execCommand("delete"); break;
      case "left": moveCaret(-1); break;
      case "right": moveCaret(1); break;
      case "enter": return enter();
      default:
        insert(id);
        if (layer === "upper") { layer = "lower"; render(); }
    }
  }

  function enter() {
    const el = target;
    const init = { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true, composed: true };
    // Let the page handle Enter first (search boxes, chat inputs); only fall back to default behaviour.
    const proceed = el.dispatchEvent(new KeyboardEvent("keydown", init));
    el.dispatchEvent(new KeyboardEvent("keypress", init));
    el.dispatchEvent(new KeyboardEvent("keyup", init));
    if (!proceed) return close();
    if (el instanceof HTMLTextAreaElement) return insert("\n");
    if (el.isContentEditable) { el.focus(); return void document.execCommand("insertParagraph"); }
    const form = el.form;
    close();
    form?.requestSubmit?.();
  }

  function render() {
    oskEl.textContent = "";
    L[layer].forEach((row, r) => {
      const rowEl = document.createElement("div");
      rowEl.className = "row";
      [...row].forEach((id, c) => {
        const k = document.createElement("div");
        const latched = id === "shift" && layer === "upper";
        k.className = "key" + (TEXT_KEYS.has(id) ? " t" : "") + (latched ? " on" : "");
        k.style.flexGrow = GROW[id] ?? 1;
        if (ICON[id]) {
          k.innerHTML = `<svg class="ic${latched ? " f" : ""}" viewBox="0 0 24 24" aria-hidden="true">${ICON[id]}</svg>`;
        } else {
          k.textContent = LABEL[id] ?? id;
        }
        k.dataset.id = id; k.dataset.r = r; k.dataset.c = c;
        k.addEventListener("click", () => {
          k.classList.add("hit");
          setTimeout(() => k.classList.remove("hit"), 110);
          press(id);
        });
        rowEl.appendChild(k);
      });
      oskEl.appendChild(rowEl);
    });
    const rows = [...oskEl.children];
    const row = rows[Math.min(lastPos.r, rows.length - 1)];
    const keys = [...row.children];
    CC.setCursor?.(keys[lastPos.last ? keys.length - 1 : Math.min(lastPos.c, keys.length - 1)]);
  }

  // Highlight the controller's selection and remember its position across layer changes.
  function mark(el) {
    for (const k of oskEl.querySelectorAll(".sel")) k.classList.remove("sel");
    if (el && oskEl.contains(el)) {
      el.classList.add("sel");
      lastPos = { r: +el.dataset.r, c: +el.dataset.c, last: !el.nextElementSibling };
    }
  }

  function openFor(el) {
    if (open || !isEditable(el)) return;
    CC.raise();
    target = el;
    open = true;
    layer = "lower";
    lastPos = { r: 2, c: 4, last: false };
    oskEl.classList.add("open");
    el.focus({ preventScroll: true });
    el.scrollIntoView({ block: "center" });
    setTimeout(() => {
      const r = el.getBoundingClientRect();
      const limit = innerHeight - oskEl.offsetHeight - 20;
      if (r.bottom > limit) window.scrollBy({ top: r.bottom - limit });
    }, 60);
    CC.onOskOpen?.();
    render();
  }

  function close() {
    if (!open) return;
    open = false;
    oskEl.classList.remove("open");
    const el = target;
    target = null;
    // Leave no field focused, otherwise the daemon's real key presses would be typed into it.
    if (el && document.activeElement === el) el.blur();
    CC.onOskClose?.(el);
  }

  CC.osk = { isEditable, open: openFor, close, mark, isOpen: () => open,
    keys: () => [...oskEl.querySelectorAll(".key")] };
})();
