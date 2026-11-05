/**
 * TodayTick 主窗端到端检查：借 WebView2 的 CDP 端口直接操作 DOM。
 * 用法：node tools/uicheck.mjs [端口=9333]
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

  await ev(cdp, `
    const s = await window.__TAURI__.core.invoke("get_state");
    for (const it of s.items) await window.__TAURI__.core.invoke("remove_reminder", { id: it.id });
    return true;
  `);
  await sleep(400);

  const empty = await ev(cdp, `
    return {
      section: document.querySelector("#section").textContent.trim(),
      rows: document.querySelectorAll(".row").length,
      hint: document.querySelector("#hint").textContent.trim(),
    };
  `);
  check("空态「待提醒 · 0」", empty.section.includes("待提醒") && empty.rows === 0, JSON.stringify(empty));
  check("空时间不重复显示格式提示", empty.hint === "", empty.hint);

  const added = await ev(cdp, `
    const desc = document.querySelector("#desc");
    const when = document.querySelector("#when");
    desc.value = "自动化检查：喝水";
    desc.dispatchEvent(new Event("input", { bubbles: true }));
    when.value = "+2分";
    when.dispatchEvent(new Event("input", { bubbles: true }));
    const hint = document.querySelector("#hint").textContent.trim();
    document.querySelector("#btn-add").click();
    await new Promise((r) => setTimeout(r, 400));
    const s = await window.__TAURI__.core.invoke("get_state");
    return {
      hint,
      count: s.items.length,
      rows: document.querySelectorAll(".row").length,
      text: document.querySelector(".row .txt")?.textContent || "",
      desc: desc.value,
      when: when.value,
    };
  `);
  check("时间提示变蓝", added.hint.includes("提醒"), added.hint);
  check("添加后 1 条", added.count === 1 && added.rows === 1, `count=${added.count} rows=${added.rows}`);
  check("列表文字正确", added.text.includes("喝水"), added.text);
  check("添加后输入框清空", added.desc === "" && added.when === "", JSON.stringify([added.desc, added.when]));

  const bad = await ev(cdp, `
    const when = document.querySelector("#when");
    when.value = "25:00";
    when.dispatchEvent(new Event("input", { bubbles: true }));
    const hint = document.querySelector("#hint").textContent.trim();
    document.querySelector("#btn-add").click();
    await new Promise((r) => setTimeout(r, 300));
    const s = await window.__TAURI__.core.invoke("get_state");
    return { hint, count: s.items.length };
  `);
  check("非法时间提示变红", bad.hint.includes("没看懂"), bad.hint);
  check("非法时间不入库", bad.count === 1, `count=${bad.count}`);

  const zh = await ev(cdp, `
    const desc = document.querySelector("#desc");
    const when = document.querySelector("#when");
    desc.value = "明天早上开会";
    desc.dispatchEvent(new Event("input", { bubbles: true }));
    when.value = "明天 9:30";
    when.dispatchEvent(new Event("input", { bubbles: true }));
    document.querySelector("#btn-add").click();
    await new Promise((r) => setTimeout(r, 400));
    const s = await window.__TAURI__.core.invoke("get_state");
    return {
      count: s.items.length,
      times: [...document.querySelectorAll(".row .t")].map((e) => e.textContent.trim()),
    };
  `);
  check("中文时间可添加", zh.count === 2, JSON.stringify(zh.times));

  const removed = await ev(cdp, `
    document.querySelector(".row .del").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 400));
    const s = await window.__TAURI__.core.invoke("get_state");
    return { count: s.items.length, rows: document.querySelectorAll(".row").length };
  `);
  check("删除一行", removed.count === 1 && removed.rows === 1, JSON.stringify(removed));

  const toggled = await ev(cdp, `
    const tg = document.querySelectorAll(".tgl");
    return {
      count: tg.length,
      sound: !!document.querySelector("#tgl-sound"),
      start: !!document.querySelector("#tgl-start"),
    };
  `);
  check(
    "底栏只剩开机自启一个开关",
    toggled.count === 1 && toggled.sound === false && toggled.start === true,
    JSON.stringify(toggled)
  );

  const many = await ev(cdp, `
    const make = (i) => {
      const d = new Date(Date.now() + (i + 1) * 3600 * 1000);
      const p = (n) => String(n).padStart(2, "0");
      return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + "T" + p(d.getHours()) + ":" + p(d.getMinutes());
    };
    for (let i = 0; i < 6; i++) {
      await window.__TAURI__.core.invoke("add_reminder", { text: "批量 " + (i + 1), when: make(i) });
    }
    await new Promise((r) => setTimeout(r, 900));
    return { rows: document.querySelectorAll(".row").length };
  `);
  check("批量添加 6 条", many.rows === 7, `rows=${many.rows}`);

  await ev(cdp, `
    const s = await window.__TAURI__.core.invoke("get_state");
    for (const it of s.items) await window.__TAURI__.core.invoke("remove_reminder", { id: it.id });
    return true;
  `);
  await sleep(600);
  const empty2 = await ev(cdp, `
    return { rows: document.querySelectorAll(".row").length, section: document.querySelector("#section").textContent.trim() };
  `);
  check("清空回到空态", empty2.rows === 0 && empty2.section.includes("0"), JSON.stringify(empty2));

  cdp.ws.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${failed.length ? "UI FAIL: " + failed.map((f) => f.name).join(", ") : "UI CHECK PASS"}`);
  return failed.length ? 1 : 0;
}

main()
  .then((code) => process.exit(code))
  .catch((err) => {
    console.error("UI 检查异常:", err.message);
    process.exit(2);
  });
