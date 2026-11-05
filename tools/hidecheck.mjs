/**
 * TodayTick 关闭/隐藏/退出流程检查（借 CDP 直接点 DOM）。
 * 用法：node tools/hidecheck.mjs [端口=9333]
 */

const PORT = process.argv[2] ? Number(process.argv[2]) : 9333;
const BASE = `http://127.0.0.1:${PORT}`;

const results = [];
function check(name, ok, extra = "") {
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${extra ? " " + extra : ""}`);
  results.push({ name, ok });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitTarget(match, timeout = 20000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    try {
      const res = await fetch(`${BASE}/json/list`);
      const list = await res.json();
      const hit = list.find((t) => t.type === "page" && match(t.url));
      if (hit) return hit;
    } catch {
      /* 端口还没起来 */
    }
    await sleep(250);
  }
  return null;
}

function connect(target) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    let seq = 0;
    const pending = new Map();
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && pending.has(msg.id)) {
        const { resolve: res, reject: rej } = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) rej(new Error(JSON.stringify(msg.error)));
        else res(msg.result);
      }
    });
    ws.addEventListener("error", reject);
    ws.addEventListener("open", () => {
      const send = (method, params = {}) =>
        new Promise((res, rej) => {
          const id = ++seq;
          pending.set(id, { resolve: res, reject: rej });
          ws.send(JSON.stringify({ id, method, params }));
        });
      resolve({ ws, send });
    });
  });
}

async function ev(cdp, expression) {
  const { result, exceptionDetails } = await cdp.send("Runtime.evaluate", {
    expression: `(async () => { ${expression} })()`,
    awaitPromise: true,
    returnByValue: true,
  });
  if (exceptionDetails) {
    throw new Error(exceptionDetails.exception?.description || JSON.stringify(exceptionDetails));
  }
  return result.value;
}

const MAIN = (u) => u.includes("tauri.localhost") && !u.includes("popup");

async function main() {
  const target = await waitTarget(MAIN);
  if (!target) {
    check("连接主窗", false, "找不到主窗页面");
    return 1;
  }
  const cdp = await connect(target);
  await cdp.send("Runtime.enable");

  const hidden = await ev(cdp, `
    document.querySelector("#btn-close").click();
    await new Promise((r) => setTimeout(r, 400));
    return { hidden: document.visibilityState === "hidden", error: document.querySelector("#section").textContent };
  `);
  check("隐藏到托盘后窗口确实隐藏", hidden.hidden === true, JSON.stringify(hidden));

  cdp.ws.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${failed.length ? "HIDE FAIL: " + failed.map((f) => f.name).join(", ") : "HIDE CHECK PASS"}`);
  return failed.length ? 1 : 0;
}

main()
  .then((code) => process.exit(code))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
