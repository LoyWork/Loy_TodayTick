/** 检查开机自启开关：invoke set_autostart 前后读注册表。node tools/autostart.mjs */
const PORT = Number(process.argv[2] || 9333);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const KEY = "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run";

async function regQuery() {
  const { execFileSync } = await import("node:child_process");
  try {
    const out = execFileSync("reg", ["query", KEY, "/v", "TodayTick"], { encoding: "utf8" });
    const line = out.split(/\r?\n/).find((l) => l.includes("TodayTick"));
    return line ? line.trim() : "";
  } catch {
    return "";
  }
}

async function target() {
  const end = Date.now() + 20000;
  while (Date.now() < end) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const hit = list.find((t) => t.type === "page" && !t.url.includes("popup"));
      if (hit) return hit;
    } catch {}
    await sleep(250);
  }
  return null;
}

function connect(t) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(t.webSocketDebuggerUrl);
    let seq = 0;
    const pending = new Map();
    ws.addEventListener("message", (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && pending.has(m.id)) {
        const p = pending.get(m.id);
        pending.delete(m.id);
        m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
      }
    });
    ws.addEventListener("error", reject);
    ws.addEventListener("open", () => {
      const send = (method, params = {}) =>
        new Promise((res, rej) => {
          const id = ++seq;
          pending.set(id, { res, rej });
          ws.send(JSON.stringify({ id, method, params }));
        });
      resolve({ ws, send });
    });
  });
}

async function ev(cdp, body) {
  const r = await cdp.send("Runtime.evaluate", {
    expression: `(async () => { ${body} })()`,
    awaitPromise: true,
    returnByValue: true,
  });
  if (r.exceptionDetails) {
    const e = r.exceptionDetails;
    const detail = e.exception?.description || e.exception?.value || e.text || JSON.stringify(e);
    throw new Error(String(detail).slice(0, 400));
  }
  return r.result.value;
}

const t = await target();
if (!t) {
  console.log("没有主窗");
  process.exit(1);
}
const cdp = await connect(t);
await cdp.send("Runtime.enable");

let fails = 0;
const check = (name, ok, extra) => {
  console.log(`${ok ? "PASS" : "FAIL"} ${name} ${extra}`);
  if (!ok) fails++;
};

// 起点：关掉
await ev(cdp, `await window.__TAURI__.core.invoke("set_autostart", { on: false }); return 1;`);
await sleep(300);
check("关闭后注册表无值", (await regQuery()) === "", await regQuery());

// 打开
const on = await ev(cdp, `return await window.__TAURI__.core.invoke("set_autostart", { on: true });`);
await sleep(300);
const reg = await regQuery();
check("打开后返回 true", on === true, String(on));
check("注册表写入 exe 路径", reg.includes("todaytick.exe"), reg);

// 前端状态
const st = await ev(cdp, `const s = await window.__TAURI__.core.invoke("get_state"); return s.autostart;`);
check("get_state 反映已开启", st === true, String(st));

// 收尾：关掉
await ev(cdp, `await window.__TAURI__.core.invoke("set_autostart", { on: false }); return 1;`);
await sleep(300);
check("关闭后注册表已清", (await regQuery()) === "", await regQuery());

cdp.ws.close();
console.log(fails === 0 ? "AUTOSTART PASS" : `AUTOSTART FAIL ${fails}`);
process.exit(fails === 0 ? 0 : 1);
