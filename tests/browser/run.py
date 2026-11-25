"""Smoke test: run the extension content scripts in headless Chrome with a stubbed chrome.* API."""
import json, pathlib, subprocess, sys, tempfile, time, urllib.request
from websockets.sync.client import connect

HERE = pathlib.Path(__file__).parent
EXT = HERE.parent.parent / "extension"
STUB = "window.__sent=[];globalThis.chrome={runtime:{sendMessage:async m=>{window.__sent.push(m)},onMessage:{addListener:f=>{window.__h=f}}}};"

proc = subprocess.Popen(["google-chrome", "--headless=new", "--remote-debugging-port=9333", "--no-sandbox",
    "--window-size=900,700", f"--user-data-dir={tempfile.mkdtemp()}", "about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json")); break
        except Exception: time.sleep(0.2)
    ws = connect([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"])
    n = 0
    def cdp(method, **params):
        global n; n += 1; ws.send(json.dumps({"id": n, "method": method, "params": params}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == n: return m
    def js(expr):
        r = cdp("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r["result"]: raise RuntimeError(r["result"]["exceptionDetails"])
        return r["result"]["result"].get("value")
    cdp("Page.enable"); cdp("Emulation.setFocusEmulationEnabled", enabled=True)
    cdp("Page.navigate", url=(HERE / "page.html").as_uri()); time.sleep(1)
    js(STUB); js((EXT / "osk.js").read_text()); js((EXT / "content.js").read_text())
    send = lambda **m: (js(f"window.__h({json.dumps(m)})"), time.sleep(0.4))
    def focused():  # element under the focus box
        return js("""(()=>{const b=window.__cc.boxEl.getBoundingClientRect();
          return b.width? document.elementFromPoint(b.left+b.width/2,b.top+b.height/2)?.id:null})()""")
    fails = []
    def check(name, got, want):
        ok = got == want; print(("PASS" if ok else "FAIL"), name, "" if ok else f"got {got!r} want {want!r}")
        if not ok: fails.append(name)

    send(type="nav", dir="down");  first = focused(); check("first nav picks something", first is not None, True)
    js("document.getElementById('a1').scrollIntoView()")
    # walk to a1 from wherever we are via keys
    for _ in range(4): send(type="nav", dir="up"); send(type="nav", dir="left")
    check("top-left reachable", focused(), "a1")
    send(type="nav", dir="right"); check("right -> a2", focused(), "a2")
    send(type="nav", dir="down");  check("down -> a5", focused(), "a5")
    send(type="nav", dir="left");  check("left -> b1", focused(), "b1")
    send(type="nav", dir="down");  check("down -> a7", focused(), "a7")
    send(type="nav", dir="right"); send(type="nav", dir="right"); check("right x2 -> a9", focused(), "a9")
    send(type="select")
    check("native link activated with a real Enter key", js("window.__sent.filter(m=>m.type==='key').map(m=>m.key)"), ["enter"])
    check("link was focused for the key", js("document.activeElement.id"), "a9")
    js("document.activeElement.blur()")
    check("display:none element never targeted", focused() != "hid", True)
    # text field -> OSK
    send(type="nav", dir="down"); check("down -> search box", focused(), "q")
    send(type="select"); check("OSK opens", js("window.__cc.osk.isOpen()"), True)
    check("search focused", js("document.activeElement.id"), "q")
    check("typing state reported", js("window.__sent.some(m=>m.type==='typing'&&m.value===true)"), True)
    sel = lambda: js("[...window.__cc.osk.keys()].filter(k=>k.classList.contains('sel')).map(k=>k.dataset.id)")
    check("cursor starts on g, one key selected", sel(), ["g"])
    def key(label):
        js(f"[...window.__cc.osk.keys()].find(k=>k.dataset.id==={json.dumps(label)}).click()"); time.sleep(0.1)
    for c in "hi": key(c)
    check("box hidden while keyboard selection is on a key", js("window.__cc.boxEl.style.display"), "none")
    # shift: cursor must stay on the shift key, then Z lands on the same spot afterwards
    js("window.__cc.setCursor([...window.__cc.osk.keys()].find(k=>k.dataset.id==='shift'))")
    send(type="select")
    check("shift keeps cursor on shift", sel(), ["shift"])
    check("shift latched", js("[...window.__cc.osk.keys()].find(k=>k.dataset.id==='shift').classList.contains('on')"), True)
    send(type="nav", dir="right"); check("right -> Z", sel(), ["Z"])
    send(type="select")
    check("capital typed, layer back to lower, cursor kept", sel(), ["z"])
    key("bksp")
    js("window.__cc.setCursor([...window.__cc.osk.keys()].find(k=>k.dataset.id==='sym'))"); send(type="select")
    check("sym toggle -> abc in the same spot", js("window.__cc.osk.keys().find(k=>k.dataset.id==='abc')?.classList.contains('sel')"), True)
    key("!")
    check("typing works", js("document.getElementById('q').value"), "hi!")
    send(type="nav", dir="up"); send(type="nav", dir="right")
    check("exactly one key selected after nav", len(sel()), 1)
    key("abc"); key("enter")
    check("enter submits form", js("window.submitted"), "hi!")
    check("OSK closed after enter", js("window.__cc.osk.isOpen()"), False)
    check("field blurred after enter", js("document.activeElement.id!=='q'"), True)
    send(type="nav", dir="down"); check("down -> custom role=button", focused(), "dv")
    send(type="select"); check("div button gets a synthetic click", js("window.clicked.slice(-1)[0]"), "dv")
    # search action finds the box and opens the keyboard; back closes and blurs
    send(type="search")
    check("search opens OSK on the search box", js("window.__cc.osk.isOpen() && document.activeElement.id"), "q")
    send(type="back")
    check("back closes OSK and blurs", js("!window.__cc.osk.isOpen() && document.activeElement.id!=='q'"), True)
    # modal dialog: only its contents are reachable, back dismisses it instead of leaving the page
    js("document.getElementById('dlg').showModal()")
    send(type="nav", dir="down"); check("modal dialog button reachable", focused(), "dbtn")
    send(type="back"); check("back closes dialog", js("document.getElementById('dlg').open"), False)
    check("page not navigated away", js("location.pathname.endsWith('page.html')"), True)
    # controls list: shows live bindings, swallows the next button press, then goes away
    js("window.__cc.showHelp && 0")
    send(type="help", bindings={"A": "select", "R3": "fullscreen", "DPAD_UP": "up", "X": "help", "Y": "none"})
    helptext = js("window.__cc.root.querySelector('.help').innerText")
    check("help open", js("window.__cc.helpIsOpen()"), True)
    check("help lists bindings (remapped R3 -> Fullscreen)", "Right stick click" in helptext and "Fullscreen" in helptext, True)
    check("help hides unbound and direction-only d-pad rows", "D-pad up" not in helptext and "Y" not in helptext.replace("Controls", ""), True)
    n_clicks = js("window.clicked.length")
    send(type="select")
    check("any button closes help without acting", js("window.__cc.helpIsOpen()") is False and js("window.clicked.length") == n_clicks, True)
    send(type="help", bindings={}); send(type="help", bindings={})
    check("help toggles", js("window.__cc.helpIsOpen()"), False)
    # mouse mode toast/pause, then resume
    send(type="mode", mouse=True)
    check("box hidden in forced mouse mode", js("window.__cc.boxEl.style.display"), "none")
    send(type="mode", mouse=False)
    check("box back after leaving mouse mode", js("window.__cc.boxEl.style.display"), "block")
    # fullscreen player: directions become real keys, A plays/pauses
    js("window.__sent.length=0; Object.defineProperty(document,'fullscreenElement',{get:()=>document.body,configurable:true})")
    send(type="nav", dir="left"); send(type="select")
    check("player mode forwards keys", js("window.__sent.filter(m=>m.type==='key').map(m=>m.key)"), ["left", "space"])
    js("document.dispatchEvent(new Event('fullscreenchange'))"); time.sleep(0.3)
    check("no focus box in fullscreen player mode", js("window.__cc.boxEl.style.display"), "none")
    js("delete document.fullscreenElement; document.dispatchEvent(new Event('fullscreenchange'))"); time.sleep(0.4)
    check("box returns after leaving fullscreen", js("window.__cc.boxEl.style.display"), "block")
    # YouTube-style auto-hiding controls: faded out (opacity 0) -> box must not hover over nothing
    js("document.getElementById('a5').parentElement.style.opacity='0'"); time.sleep(0.4)
    send(type="nav", dir="up")   # land somewhere in the faded grid
    time.sleep(0.4)
    check("box hidden over invisible element", js("window.__cc.boxEl.style.display"), "none")
    js("document.getElementById('a5').parentElement.style.opacity='1'"); time.sleep(0.4)
    check("box back when it fades in", js("window.__cc.boxEl.style.display"), "block")
    # real keyboard / mouse input hides the box until the pad is touched again (and never acts blind)
    display = lambda: js("window.__cc.boxEl.style.display")
    mouse = lambda x, y: cdp("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
    shift = lambda t: cdp("Input.dispatchKeyEvent", type=t, key="Shift", code="ShiftLeft", windowsVirtualKeyCode=16)
    send(type="nav", dir="down"); before = focused()
    check("box visible before real input", display(), "block")
    js("dispatchEvent(new MouseEvent('mousemove',{screenX:10,screenY:10}));dispatchEvent(new MouseEvent('mousemove',{screenX:400,screenY:300}))")
    time.sleep(0.3)
    check("script-made mouse events don't hide the box", display(), "block")
    mouse(100, 100); mouse(103, 100); time.sleep(0.2)
    check("a 3px twitch of the real mouse still counts", display(), "none")
    n_clicks = js("window.clicked.length"); n_keys = js("window.__sent.filter(m=>m.type==='key').length")
    send(type="select")
    check("first A after mouse use only brings the box back, no click", js("window.clicked.length") == n_clicks
          and js("window.__sent.filter(m=>m.type==='key').length") == n_keys and display() == "block" and focused() == before, True)
    shift("keyDown"); shift("keyUp"); time.sleep(0.45)
    check("real keyboard hides the box", display(), "none")
    send(type="nav", dir="down")
    check("first stick push after keyboard use shows the box where it was", (display(), focused()), ("block", before))
    # keys the daemon presses itself arrive in either order around its "ctl" note and must not count
    js("window.__h({type:'ctl'})"); shift("keyDown"); shift("keyUp"); time.sleep(0.45)
    check("daemon key right after ctl keeps the box", display(), "block")
    shift("keyDown"); shift("keyUp"); time.sleep(0.1); js("window.__h({type:'ctl'})"); time.sleep(0.45)
    check("daemon key that beats its ctl note keeps the box", display(), "block")
    # the on-screen keyboard's selection goes too
    send(type="search")
    keys_sel = lambda: js("[...window.__cc.osk.keys()].filter(k=>k.classList.contains('sel')).map(k=>k.dataset.id)")
    sel_before = keys_sel(); osk_idle = lambda: js("window.__cc.root.querySelector('.osk').classList.contains('idle')")
    check("OSK open with a selected key, not idle", (js("window.__cc.osk.isOpen()"), len(sel_before), osk_idle()), (True, 1, False))
    shift("keyDown"); shift("keyUp"); time.sleep(0.45)
    check("real keyboard dims the OSK selection", osk_idle(), True)
    send(type="nav", dir="right")
    check("pad brings it back on the same key", (osk_idle(), keys_sel()), (False, sel_before))
    send(type="back")
    ws.close()
    print("\nFAILED:" if fails else "\nALL PASSED", fails or "")
    sys.exit(1 if fails else 0)
finally:
    proc.terminate()
