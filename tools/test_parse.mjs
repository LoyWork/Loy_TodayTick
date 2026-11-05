/* 时间解析自测：node tools/test_parse.mjs */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const code = readFileSync(join(root, "ui", "parse.js"), "utf8");
const sandbox = { Date, String, Number, Math, console };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const TTP = sandbox.TTP;

const now = new Date(2026, 10, 5, 14, 31, 0); // 2026-11-05 14:31 本地
let pass = 0;
const fails = [];

function iso(d) {
  return (
    d.getFullYear() +
    "-" +
    String(d.getMonth() + 1).padStart(2, "0") +
    "-" +
    String(d.getDate()).padStart(2, "0") +
    "T" +
    String(d.getHours()).padStart(2, "0") +
    ":" +
    String(d.getMinutes()).padStart(2, "0")
  );
}

function ok(name, got, want) {
  if (got === want) {
    pass++;
  } else {
    fails.push(`${name}: got ${JSON.stringify(got)} want ${JSON.stringify(want)}`);
  }
}

function parsed(raw) {
  return iso(TTP.parseTarget(raw, now).date);
}

ok("14:35", parsed("14:35"), "2026-11-05T14:35");
ok("09:05 已过→明天", parsed("9:05"), "2026-11-06T09:05");
ok("9点 已过→明天", parsed("9点"), "2026-11-06T09:00");
ok("9点30分", parsed("9点30分"), "2026-11-06T09:30");
ok("9点半", parsed("9点半"), "2026-11-06T09:30");
ok("21点30分", parsed("21点30分"), "2026-11-05T21:30");
ok("1435", parsed("1435"), "2026-11-05T15:00".replace("15:00", "14:35"));
ok("14:00 已过→明天", parsed("14:00"), "2026-11-06T14:00");
ok("明天 9:00", parsed("明天 9:00"), "2026-11-06T09:00");
ok("后天 8点", parsed("后天 8点"), "2026-11-07T08:00");
ok("大后天 10:30", parsed("大后天 10:30"), "2026-11-08T10:30");
ok("11-07 08:30", parsed("11-07 08:30"), "2026-11-07T08:30");
ok("已过的月日→明年", parsed("01-02 08:30"), "2027-01-02T08:30");
ok("2026-12-01 07:15", parsed("2026-12-01 07:15"), "2026-12-01T07:15");
ok("明早", parsed("明早"), "2026-11-06T09:00");
ok("+5分", parsed("+5分"), "2026-11-05T14:36");
ok("+30分钟", parsed("+30分钟"), "2026-11-05T15:01");
ok("+1小时", parsed("+1小时"), "2026-11-05T15:31");
ok("+1.5小时", parsed("+1.5小时"), "2026-11-05T16:01");
ok("全角冒号", parsed("21：45"), "2026-11-05T21:45");

for (const bad of ["", "下午", "25:00", "13:70", "1-1", "abc", "+0分"]) {
  let threw = false;
  try {
    TTP.parseTarget(bad, now);
  } catch (e) {
    threw = true;
  }
  ok(`拒绝 ${JSON.stringify(bad)}`, threw, true);
}

ok("formatWhen 今天", TTP.formatWhen(new Date(2026, 10, 5, 9, 5), now), "09:05");
ok("formatWhen 明天", TTP.formatWhen(new Date(2026, 10, 6, 9, 0), now), "明天 09:00");
ok("formatWhen 后天", TTP.formatWhen(new Date(2026, 10, 7, 8, 0), now), "后天 08:00");
ok("formatWhen 跨月", TTP.formatWhen(new Date(2026, 11, 1, 7, 15), now), "12-01 07:15");
ok("formatWhen 跨年", TTP.formatWhen(new Date(2027, 0, 2, 8, 30), now), "2027-01-02 08:30");
ok("formatRow 明天", TTP.formatRow(new Date(2026, 10, 6, 9, 0), now), "明 09:00");
ok("toIso", TTP.toIso(new Date(2026, 10, 5, 8, 7)), "2026-11-05T08:07");
ok("fromIso", iso(TTP.fromIso("2026-11-05T08:07")), "2026-11-05T08:07");

console.log(`通过 ${pass} 项`);
if (fails.length) {
  console.log("FAIL");
  fails.forEach((f) => console.log("  " + f));
  process.exit(1);
}
console.log("PARSE TEST PASS");
