// Bridges the ControllerController daemon (ws://127.0.0.1:8765) and the page content scripts.
const api = globalThis.browser ?? globalThis.chrome;
const URL = "ws://127.0.0.1:8765";

let ws = null;
const focusedTabs = new Set();
let lastReported = null;

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function reportActive() {
  const value = focusedTabs.size > 0;
  if (value !== lastReported) {
    lastReported = value;
    send({ type: "active", value });
  }
}

async function activeTab() {
  const [tab] = await api.tabs.query({ active: true, lastFocusedWindow: true });
  return tab;
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  try {
    ws = new WebSocket(URL);
  } catch {
    return;
  }
  ws.onopen = () => {
    lastReported = null;
    reportActive();
  };
  ws.onmessage = async (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === "ping") return;
    const tab = await activeTab();
    if (tab) api.tabs.sendMessage(tab.id, msg).catch(() => {});
  };
  ws.onclose = () => { ws = null; setTimeout(connect, 2000); };
  ws.onerror = () => { try { ws.close(); } catch {} };
}

api.runtime.onMessage.addListener((msg, sender) => {
  const id = sender.tab?.id;
  if (msg.type === "focus" && id != null) {
    if (msg.value) focusedTabs.add(id); else focusedTabs.delete(id);
    reportActive();
  } else if (msg.type === "typing" || msg.type === "key") {
    send(msg);
  }
});
api.tabs.onRemoved.addListener((id) => { focusedTabs.delete(id); reportActive(); });
// A navigating tab may land on a page without our content script (about:, PDF viewer, ...);
// drop its focus flag now and let the new page's script report again.
api.tabs.onUpdated.addListener((id, change) => {
  if (change.status === "loading" && focusedTabs.delete(id)) reportActive();
});

// Content scripts only load into pages opened after install; inject into the tabs already open.
api.runtime.onInstalled.addListener(async () => {
  const tabs = await api.tabs.query({ url: ["http://*/*", "https://*/*"] });
  for (const tab of tabs) {
    api.scripting.executeScript({ target: { tabId: tab.id }, files: ["osk.js", "content.js"] }).catch(() => {});
  }
});

// Wake the worker periodically so it reconnects after being suspended (Firefox event pages
// are not kept alive by socket traffic; the daemon re-asks for focus state on every connect).
api.alarms.create("keepalive", { periodInMinutes: 0.5 });
api.alarms.onAlarm.addListener(connect);
connect();
