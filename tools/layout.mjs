/** 布局体检：把主窗/弹窗里每个元素的位置量出来，检查越界与重叠。
 *  用法：node tools/layout.mjs [port]
 *  需先用带 --remote-debugging-port 的方式启动应用。
 */
const PORT = Number(process.argv[2] || 9333);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function listTargets() {
  const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
  return res.json();
}

async function waitTarget(match, timeout = 20000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    try {
      const hit = (await listTargets()).find((t) => t.type === "page" && match(t.url));
      if (hit) return hit;
    } catch {}
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
        const p = pending.get(msg.id);
        pending.delete(msg.id);
        msg.error ? p.rej(new Error(JSON.stringify(msg.error))) : p.res(msg.result);
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

async function ev(cdp, expr) {
  const r = await cdp.send("Runtime.evaluate", {
    expression: `(async () => { ${expr} })()`,
    awaitPromise: true,
    returnByValue: true,
  });
  if (r.exceptionDetails) {
    throw new Error(r.exceptionDetails.exception?.description || "eval failed");
  }
  return r.result.value;
}

const CMD = `
  const sels = [
    ["shell", "#shell"],
    ["header", "header"],
    ["brand", ".brand"],
    ["clock", "#clock"],
    ["close", "#btn-close"],
    ["composer", ".composer"],
    ["desc", "#desc"],
    ["when", "#when"],
    ["hint", "#hint"],
    ["add", "#btn-add"],
    ["section", "#section"],
    ["listwrap", ".listwrap"],
    ["list", "#list"],
    ["row0", ".list .row"],
    ["foot", "footer"],
    ["tgl-start", "#tgl-start"],
    ["keyhint", ".keyhint"]
  ];
  const out = {};
  for (const [name, sel] of sels) {
    const el = document.querySelector(sel);
    if (!el) { out[name] = null; continue; }
    const r = el.getBoundingClientRect();
    out[name] = {
      x: Math.round(r.x), y: Math.round(r.y),
      w: Math.round(r.width), h: Math.round(r.height),
      text: (el.innerText || "").trim().slice(0, 24).replace(/\\s+/g, " ")
    };
  }
  out._win = { w: window.innerWidth, h: window.innerHeight };
  out._scroll = { listScrollH: document.querySelector("#list")?.scrollHeight || 0, listH: Math.round(document.querySelector("#list")?.getBoundingClientRect().height || 0) };
  return out;
`;

function check(name, ok, extra) {
  console.log(`${ok ? "PASS" : "FAIL"} ${name} ${extra}`);
  return ok ? 0 : 1;
}

function overlap(a, b) {
  if (!a || !b) return false;
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

async function mainWindow() {
  const t = await waitTarget((u) => !u.includes("popup"));
  if (!t) throw new Error("没有主窗");
  const cdp = await connect(t);
  await cdp.send("Runtime.enable");
  await sleep(400);
  const m = await ev(cdp, CMD);
  cdp.ws.close();

  let fails = 0;
  const order = ["header", "composer", "section", "listwrap", "foot"];
  for (const k of order) {
    if (!m[k]) {
      fails += check(`元素存在 ${k}`, false, "");
      continue;
    }
  }
  if (m.shell) {
    fails += check("shell 撑满窗口", m.shell.w === m._win.w && m.shell.h === m._win.h, `${m.shell.w}x${m.shell.h} win ${m._win.w}x${m._win.h}`);
  }
  // 纵向顺序：header < composer < section < listwrap < foot
  const seq = order.filter((k) => m[k]);
  let ordered = true;
  for (let i = 1; i < seq.length; i++) {
    if (m[seq[i]].y < m[seq[i - 1]].y + m[seq[i - 1]].h - 1) ordered = false;
  }
  fails += check("纵向顺序正确", ordered, seq.map((k) => `${k}@${m[k].y}`).join(" "));
  // 底栏贴底（shell 自身有 ~7px 内边距）
  if (m.foot && m.shell) {
    const gap = m.shell.h - (m.foot.y + m.foot.h);
    fails += check("底栏贴底", gap >= 0 && gap <= 12, `gap=${gap}`);
  }
  // 控件不重叠
  const pairs = [["when", "add"], ["clock", "close"]];
  for (const [a, b] of pairs) {
    if (m[a] && m[b]) fails += check(`不重叠 ${a}/${b}`, !overlap(m[a], m[b]), "");
  }
  // 输入框在 composer 内
  for (const k of ["desc", "when", "add"]) {
    if (m[k] && m.composer) {
      const inside =
        m[k].x >= m.composer.x - 1 &&
        m[k].x + m[k].w <= m.composer.x + m.composer.w + 1 &&
        m[k].y >= m.composer.y - 1 &&
        m[k].y + m[k].h <= m.composer.y + m.composer.h + 1;
      if (k !== "add") fails += check(`${k} 在输入卡内`, inside, "");
    }
  }
  // 提示文字不与时间框重叠
  if (m.hint && m.when) fails += check("提示不压时间框", !overlap(m.hint, m.when), `hint.x=${m.hint.x} when.right=${m.when.x + m.when.w}`);
  // 列表不越界
  if (m.listwrap && m.shell) {
    const fits = m.listwrap.y + m.listwrap.h <= m.shell.h + 1;
    fails += check("列表不越界", fits, `bottom=${m.listwrap.y + m.listwrap.h} shell=${m.shell.h}`);
  }
  // 44px 行距给时间和提醒内容留出清楚的阅读节奏。
  if (m.row0) fails += check("行高至少 44", m.row0.h >= 44 && m.row0.h <= 54, `h=${m.row0.h}`);
  // 时钟/关闭在 header 内
  console.log("--- 元素坐标 ---");
  for (const [k, v] of Object.entries(m)) {
    if (k.startsWith("_") || !v) continue;
    console.log(`  ${k.padEnd(10)} ${String(v.x).padStart(4)},${String(v.y).padStart(4)} ${String(v.w).padStart(4)}x${String(v.h).padStart(3)}  ${v.text}`);
  }
  return fails;
}

async function popupWindow() {
  const t = await waitTarget((u) => u.includes("popup.html"));
  if (!t) {
    console.log("SKIP 没有弹窗");
    return 0;
  }
  const cdp = await connect(t);
  await cdp.send("Runtime.enable");
  await sleep(400);
  const m = await ev(
    cdp,
    `
    const pick = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height), text: (el.innerText||"").trim().slice(0,26).replace(/\\s+/g," ") };
    };
    return {
      card: pick(".pcard"), time: pick("#ptime"), flag: pick("#pflag"),
      text: pick("#ptext"), ack: pick("#ack"), snooze: pick("#snooze"),
      win: { w: window.innerWidth, h: window.innerHeight },
      cardH: document.querySelector(".pcard")?.scrollHeight || 0
    };
  `
  );
  cdp.ws.close();
  let fails = 0;
  fails += check("弹窗卡片存在", !!m.card, m.card ? `${m.card.w}x${m.card.h}` : "");
  fails += check("卡片不超出窗口", m.card && m.card.w <= m.win.w + 1 && m.card.h <= m.win.h + 4, `card ${m.card?.w}x${m.card?.h} win ${m.win.w}x${m.win.h}`);
  fails += check("按钮不重叠", !overlap(m.ack, m.snooze), "");
  fails += check("按钮在卡片内", m.ack && m.card && m.ack.y + m.ack.h <= m.card.y + m.card.h + 1, "");
  fails += check("描述不与按钮重叠", !overlap(m.text, m.ack), `text.bottom=${m.text ? m.text.y + m.text.h : "?"} ack.y=${m.ack?.y}`);
  fails += check("时间/描述不重叠", !overlap(m.time, m.text), "");
  console.log("--- 弹窗坐标 ---");
  for (const k of ["card", "time", "flag", "text", "ack", "snooze"]) {
    const v = m[k];
    if (!v) continue;
    console.log(`  ${k.padEnd(8)} ${String(v.x).padStart(4)},${String(v.y).padStart(4)} ${String(v.w).padStart(4)}x${String(v.h).padStart(3)}  ${v.text}`);
  }
  return fails;
}

const total = (await mainWindow()) + (await popupWindow());
console.log(total === 0 ? "LAYOUT PASS" : `LAYOUT FAIL ${total}`);
process.exit(total === 0 ? 0 : 1);
