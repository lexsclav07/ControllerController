// On-screen keyboard + the shadow-DOM overlay shared with content.js.
(() => {
  if (window.top !== window || window.__cc) return;
  const CC = (window.__cc = {});

  const host = document.createElement("div");
  host.id = "__controllercontroller";
  host.style.cssText = "all:initial;position:fixed;inset:0;pointer-events:none;z-index:2147483647;";
  const root = host.attachShadow({ mode: "closed" });
  root.innerHTML = `<style>
    .osk{position:fixed;left:0;right:0;bottom:0;padding:14px 18px 18px;background:rgba(18,18,22,.96);
      box-shadow:0 -6px 30px rgba(0,0,0,.5);font:600 22px system-ui,sans-serif;display:none;
      pointer-events:none;color:#fff}
    .osk.open{display:block}
    .row{display:flex;gap:8px;justify-content:center;margin:8px 0}
    .key{flex:1 1 0;max-width:84px;min-height:54px;border-radius:10px;background:#34343c;display:flex;
      align-items:center;justify-content:center;user-select:none}
    .key.wide{flex:2 1 0;max-width:170px}.key.space{flex:6 1 0;max-width:520px}
    .key.on{background:#4a6fff}
    .box{position:fixed;left:0;top:0;width:0;height:0;display:none;box-sizing:border-box;
      border:3px solid #fff;outline:3px solid #1a73e8;border-radius:8px;
      box-shadow:0 0 0 2px rgba(0,0,0,.55),0 4px 18px rgba(0,0,0,.45);
      transition:transform .08s ease-out,width .08s ease-out,height .08s ease-out}
  </style><div class="osk"></div><div class="box"></div>`;
  CC.host = host;
  CC.root = root;
  CC.boxEl = root.querySelector(".box");
  const oskEl = root.querySelector(".osk");
  document.documentElement.appendChild(host);

  const L = {
    lower: ["1234567890", "qwertyuiop", "asdfghjkl'", ["shift", ..."zxcvbnm", "bksp"],
      ["sym", "@", "space", ".", "-", "left", "right", "enter", "close"]],
    upper: ["1234567890", "QWERTYUIOP", 'ASDFGHJKL"', ["shift", ..."ZXCVBNM", "bksp"],
      ["sym", "@", "space", ".", "-", "left", "right", "enter", "close"]],
    sym: ["!@#$%^&*()", "~`|\\/:;?_=", "+[]{}<>,.-", ["shift", "#", "$", "%", "&", "*", "bksp"],
      ["abc", "@", "space", ".", "-", "left", "right", "enter", "close"]],
  };
  const LABEL = { shift: "⇧", bksp: "⌫", sym: "?123", abc: "ABC", space: "space", left: "◀",
    right: "▶", enter: "⏎", close: "✕" };
  const WIDE = new Set(["shift", "bksp", "sym", "abc", "enter"]);

  let target = null, layer = "lower", open = false;

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
    try {
      if (target.isContentEditable) {
        getSelection().modify("move", delta < 0 ? "backward" : "forward", "character");
      } else {
        const p = Math.max(0, target.selectionStart + delta);
        target.setSelectionRange(p, p);
      }
    } catch {}
  }

  function press(id) {
    if (!target || !target.isConnected) return close();
    switch (id) {
      case "shift": layer = layer === "lower" ? "upper" : "lower"; return render("shift");
      case "sym": layer = "sym"; return render("sym");
      case "abc": layer = "lower"; return render("abc");
      case "close": return close();
      case "space": insert(" "); break;
      case "bksp": target.focus({ preventScroll: true }); document.execCommand("delete"); break;
      case "left": moveCaret(-1); break;
      case "right": moveCaret(1); break;
      case "enter": return enter();
      default:
        insert(id);
        if (layer === "upper") { layer = "lower"; render(id); }
    }
  }

  function enter() {
    const el = target;
    if (el instanceof HTMLTextAreaElement) return insert("\n");
    if (el.isContentEditable) { el.focus(); return void document.execCommand("insertParagraph"); }
    const init = { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true };
    const proceed = el.dispatchEvent(new KeyboardEvent("keydown", init));
    el.dispatchEvent(new KeyboardEvent("keypress", init));
    el.dispatchEvent(new KeyboardEvent("keyup", init));
    close();
    if (proceed && el.form) el.form.requestSubmit?.();
  }

  function render(keepId) {
    oskEl.textContent = "";
    for (const row of L[layer]) {
      const rowEl = document.createElement("div");
      rowEl.className = "row";
      for (const id of row) {
        const k = document.createElement("div");
        k.className = "key" + (WIDE.has(id) ? " wide" : "") + (id === "space" ? " space" : "") +
          (id === "shift" && layer === "upper" ? " on" : "");
        k.textContent = LABEL[id] ?? id;
        k.dataset.id = id;
        k.addEventListener("click", () => press(id));
        rowEl.appendChild(k);
      }
      oskEl.appendChild(rowEl);
    }
    if (keepId && CC.setCursor) {
      CC.setCursor(oskEl.querySelector(`[data-id="${CSS.escape(keepId)}"]`) ?? oskEl.querySelector(".key"));
    }
  }

  function openFor(el) {
    if (open || !isEditable(el)) return;
    target = el;
    open = true;
    layer = "lower";
    oskEl.classList.add("open");
    el.focus({ preventScroll: true });
    el.scrollIntoView({ block: "center" });
    setTimeout(() => {
      const r = el.getBoundingClientRect();
      const limit = innerHeight - oskEl.offsetHeight - 20;
      if (r.bottom > limit) window.scrollBy({ top: r.bottom - limit });
    }, 60);
    CC.onOskOpen?.();
    render("g");
  }

  function close() {
    if (!open) return;
    open = false;
    oskEl.classList.remove("open");
    const el = target;
    target = null;
    CC.onOskClose?.(el);
  }

  CC.osk = { isEditable, open: openFor, close, isOpen: () => open,
    keys: () => [...oskEl.querySelectorAll(".key")] };
})();
