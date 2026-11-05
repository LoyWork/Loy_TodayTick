/* 用 WebView2 的 CDP 给窗口截图：node tools/shot.mjs [输出目录]
   需要先以 WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333 启动应用。 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const PORT = 9333;
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = process.argv[2] || join(root, "docs");
mkdirSync(outDir, { recursive: true });

function cdp(url) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url);
    let id = 0;
    const pendings = new Map();
    ws.addEventListener("open", () => resolve({ send, close: () => ws.close() }));
    ws.addEventListener("error", (e) => reject(e));
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && pendings.has(msg.id)) {
        const { resolve: res, reject: rej } = pendings.get(msg.id);
        pendings.delete(msg.id);
        if (msg.error) rej(new Error(JSON.stringify(msg.error)));
        else res(msg.result);
      }
    });
    function send(method, params = {}) {
      const mid = ++id;
      return new Promise((res, rej) => {
        pendings.set(mid, { resolve: res, reject: rej });
        ws.send(JSON.stringify({ id: mid, method, params }));
      });
    }
  });
}

const targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const pages = targets.filter((t) => t.type === "page" && t.webSocketDebuggerUrl);
if (!pages.length) {
  console.error("没有找到页面目标，应用是否带 remote-debugging-port 启动？");
  process.exit(1);
}

for (const page of pages) {
  const name = /popup\.html/.test(page.url) ? "popup" : "main";
  const conn = await cdp(page.webSocketDebuggerUrl);
  await conn.send("Page.enable");
  const shot = await conn.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
    fromSurface: true,
  });
  const file = join(outDir, `${name}.png`);
  writeFileSync(file, Buffer.from(shot.data, "base64"));
  console.log(`saved ${file}  ${page.url}`);
  conn.close();
}
