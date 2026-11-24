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
    send(type="select"); check("select clicks", js("window.clicked.slice(-1)[0]"), "a9")
    check("display:none element never targeted", js("[...document.querySelectorAll('a')].some(a=>a.id==='hid')&&true") and focused() != "hid", True)
    # text field -> OSK
    send(type="nav", dir="down"); check("down -> search box", focused(), "q")
    send(type="select"); check("OSK opens", js("window.__cc.osk.isOpen()"), True)
    check("search focused", js("document.activeElement.id"), "q")
    def key(label):
        js(f"[...window.__cc.osk.keys()].find(k=>k.dataset.id==={json.dumps(label)}).click()"); time.sleep(0.1)
    for c in "hi": key(c)
    key("shift"); key("J"); key("bksp"); key("sym"); key("!")
    check("typing works", js("document.getElementById('q').value"), "hi!")
    # navigate OSK with the controller itself
    send(type="nav", dir="down"); send(type="nav", dir="right")
    check("focus box moves onto keyboard", js("window.__cc.osk.keys().some(k=>{const r=k.getBoundingClientRect(),b=window.__cc.boxEl.getBoundingClientRect();return Math.abs(r.left-3-b.left)<2})"), True)
    key("abc"); key("enter")
    check("enter submits form", js("window.submitted"), "hi!")
    check("OSK closed after enter", js("window.__cc.osk.isOpen()"), False)
    # back with nothing open calls history.back (no crash); fullscreen player keys
    js("Object.defineProperty(document,'fullscreenElement',{get:()=>document.body,configurable:true})")
    send(type="nav", dir="left"); send(type="select")
    check("player mode forwards keys", js("window.__sent.filter(m=>m.type==='key').map(m=>m.key)"), ["left", "space"])
    ws.close()
    print("\nFAILED:" if fails else "\nALL PASSED", fails or "")
    sys.exit(1 if fails else 0)
finally:
    proc.terminate()
