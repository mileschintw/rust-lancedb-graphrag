// Q8: headless Chrome + raw CDP (Node 22+ global WebSocket, no npm packages) screenshot of a Grafana dashboard.
// Login is avoided: Network.setExtraHTTPHeaders adds HTTP Basic auth to every request of the page (Grafana accepts basic auth).
// Usage: node shot_grafana.cjs <url> <out.png> [user] [password] [widthxheight]
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const [url, out, user = "admin", pass = "admin", size = "1600x1400"] = process.argv.slice(2);
const [w, h] = size.split("x").map(Number);
const chrome = process.env.CHROME_EXE || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const port = 9333 + Math.floor(Math.random() * 500);
const prof = fs.mkdtempSync(path.join(os.tmpdir(), "chrome-cdp-"));
const proc = spawn(chrome, ["--headless=new", "--disable-gpu", "--hide-scrollbars", `--user-data-dir=${prof}`,
  `--remote-debugging-port=${port}`, "--remote-allow-origins=*", `--window-size=${w},${h}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  let ws;
  try {
    let targets;
    for (let i = 0; i < 50; i++) {
      try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); if (targets.length) break; } catch {}
      await sleep(200);
    }
    const page = targets.find((t) => t.type === "page");
    ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
    let id = 0; const pending = new Map(); const events = [];
    ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } else events.push(d.method); };
    const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
    await send("Network.enable");
    await send("Network.setExtraHTTPHeaders", { headers: { Authorization: "Basic " + Buffer.from(`${user}:${pass}`).toString("base64") } });
    await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
    await send("Page.enable");
    await send("Page.navigate", { url });
    for (let i = 0; i < 60 && !events.includes("Page.loadEventFired"); i++) await sleep(250);
    await sleep(8000); // let the panels query Prometheus/Loki and paint
    const shot = await send("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(out, Buffer.from(shot.result.data, "base64"));
    console.log("wrote", out, fs.statSync(out).size, "bytes");
  } finally { try { ws && ws.close(); } catch {} proc.kill(); await sleep(500); try { fs.rmSync(prof, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 }); } catch {} }
})().catch((e) => { console.error("FAILED", e); process.exit(1); });
