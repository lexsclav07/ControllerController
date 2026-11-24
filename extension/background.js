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
  } else if (msg.type === "key") {
    send({ type: "key", key: msg.key });
  }
});
api.tabs.onRemoved.addListener((id) => { focusedTabs.delete(id); reportActive(); });

// Wake the worker periodically so it reconnects after being suspended.
api.alarms.create("keepalive", { periodInMinutes: 0.5 });
api.alarms.onAlarm.addListener(connect);
connect();
