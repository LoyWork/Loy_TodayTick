/**
 * TodayTick 弹窗检查：需要 exe 启动前用「两条已到期」的 reminders.json 播种。
 * 用法：node tools/popupcheck.mjs [端口=9333]
 */

const PORT = process.argv[2] ? Number(process.argv[2]) : 9333;
const BASE = `http://127.0.0.1:${PORT}`;

const results = [];
function check(name, ok, extra = "") {
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${extra ? " " + extra : ""}`);
  results.push({ name, ok });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitTarget(match, timeout = 25000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    try {
      const res = await fetch(`${BASE}/json/list`);
      const list = await res.json();
      const hit = list.find((t) => t.type === "page" && match(t.url));
      if (hit) return hit;
    } catch {
      /* ignore */
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
const POPUP = (u) => u.includes("popup.html");

async function main() {
  const popupTarget = await waitTarget(POPUP);
  if (!popupTarget) {
    check("弹窗页面出现", false, "25 秒内没有弹窗");
    return 1;
  }
  const popup = await connect(popupTarget);
  await popup.send("Runtime.enable");
  await sleep(900);

  const mainTarget = await waitTarget(MAIN);
  const main = mainTarget ? await connect(mainTarget) : null;
  if (main) await main.send("Runtime.enable");

  const first = await ev(popup, `
    return {
      text: document.querySelector("#ptext").textContent.trim(),
      time: document.querySelector("#ptime").textContent.trim(),
      flagHidden: document.querySelector("#pflag").hidden,
      w: document.documentElement.scrollWidth,
      h: document.documentElement.scrollHeight,
    };
  `);
  check("弹窗显示最早的那条", first.text.includes("第一条"), JSON.stringify(first));
  check("过期标记可见", first.flagHidden === false, `hidden=${first.flagHidden}`);
  check("弹窗尺寸合理", first.w === 320 && first.h >= 100 && first.h <= 260, `${first.w}x${first.h}`);

  const snoozed = await ev(popup, `
    document.querySelector("#snooze").click();
    await new Promise((r) => setTimeout(r, 1200));
    return true;
  `);
  await sleep(1200);

  const state1 = await ev(main, `
    const s = await window.__TAURI__.core.invoke("get_state");
    const it = s.items.find((i) => i.text.includes("第一条"));
    return { found: !!it, when: it?.when || "", fired: it?.fired };
  `);
  const snoozeOk = state1.found && state1.fired === false;
  check("「稍后 5 分钟」保留且未触发", snoozeOk, JSON.stringify(state1));

  const second = await ev(popup, `
    return {
      text: document.querySelector("#ptext").textContent.trim(),
      time: document.querySelector("#ptime").textContent.trim(),
      shown: document.visibilityState,
    };
  `);
  check("自动切到下一条", second.text.includes("第二条"), JSON.stringify(second));

  await ev(popup, `
    document.querySelector("#ack").click();
    await new Promise((r) => setTimeout(r, 1200));
    return true;
  `);
  await sleep(1200);

  const state2 = await ev(main, `
    const s = await window.__TAURI__.core.invoke("get_state");
    const cur = await window.__TAURI__.core.invoke("current_popup");
    return {
      titles: s.items.map((i) => i.text),
      curIsNull: cur === null,
    };
  `);
  check("「知道了」移除该条", !state2.titles.some((t) => t.includes("第二条")), JSON.stringify(state2.titles));
  check("弹窗队列已清空", state2.curIsNull === true, JSON.stringify(state2));

  if (main) main.ws.close();
  popup.ws.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${failed.length ? "POPUP FAIL: " + failed.map((f) => f.name).join(", ") : "POPUP CHECK PASS"}`);
  return failed.length ? 1 : 0;
}

main()
  .then((code) => process.exit(code))
  .catch((err) => {
    console.error("弹窗检查异常:", err.message);
    process.exit(2);
  });
