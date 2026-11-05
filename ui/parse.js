/* TodayTick · 时间解析（纯函数，无依赖；Node 与浏览器通用） */
(function (root) {
  "use strict";

  var DAY = 86400000;

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function Bad(message) {
    var err = new Error(message || "时间没看懂");
    err.name = "TimeParseError";
    return err;
  }

  function startOfDay(d) {
    var x = new Date(d.getTime());
    x.setHours(0, 0, 0, 0);
    return x;
  }

  function validHM(h, m) {
    return (
      Number.isInteger(h) && Number.isInteger(m) && h >= 0 && h <= 23 && m >= 0 && m <= 59
    );
  }

  /* 14:35 / 14：35 / 9点 / 9点半 / 9点30分 / 9点30 / 1435 */
  function parseTimePart(s) {
    var m = /^(\d{1,2})\s*[:：]\s*(\d{1,2})$/.exec(s);
    if (m) return [parseInt(m[1], 10), parseInt(m[2], 10)];

    m = /^(\d{1,2})\s*点\s*(半|(\d{1,2})\s*分?)?$/.exec(s);
    if (m) {
      var h = parseInt(m[1], 10);
      if (m[2] === "半") return [h, 30];
      if (m[3] !== undefined) return [h, parseInt(m[3], 10)];
      return [h, 0];
    }

    m = /^(\d{3,4})$/.exec(s);
    if (m) {
      var v = m[1].padStart(4, "0");
      return [parseInt(v.slice(0, 2), 10), parseInt(v.slice(2), 10)];
    }

    return null;
  }

  var DAY_WORDS = { 今天: 0, 今晚: 0, 明天: 1, 明早: 1, 后天: 2, 大后天: 3 };

  function parseTarget(raw, now) {
    var nowD = now ? new Date(now.getTime()) : new Date();
    var s = String(raw == null ? "" : raw).trim().replace(/：/g, ":").replace(/\s+/g, " ");
    if (!s) throw Bad();

    /* 相对：+5分 / +30分钟 / +1小时 / +1.5小时 */
    var m = /^\+\s*(\d+(?:\.\d+)?)\s*(分钟|分|min|小时|时|h)$/i.exec(s);
    if (m) {
      var n = parseFloat(m[1]);
      if (!(n > 0)) throw Bad();
      var unit = m[2].toLowerCase();
      var ms = unit === "小时" || unit === "时" || unit === "h" ? n * 3600000 : n * 60000;
      return { date: new Date(nowD.getTime() + ms), rel: true };
    }

    /* 今天 / 明天 / 后天 / 大后天 前缀 */
    var dayOffset = null;
    m = /^(今天|今晚|明天|明早|后天|大后天)\s*(.*)$/.exec(s);
    if (m) {
      dayOffset = DAY_WORDS[m[1]];
      s = m[2].trim();
      if (!s) {
        if (m[1] === "明早") s = "9点";
        else if (m[1] === "今晚") s = "20点";
        else throw Bad();
      }
    }

    /* 完整日期：2026-12-01 07:15 */
    m = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})[ T]+(.+)$/.exec(s);
    if (m) {
      var y = parseInt(m[1], 10);
      var mo = parseInt(m[2], 10) - 1;
      var dd = parseInt(m[3], 10);
      var t1 = parseTimePart(m[4].trim());
      if (!t1 || !validHM(t1[0], t1[1])) throw Bad();
      var d1 = new Date(y, mo, dd, t1[0], t1[1], 0, 0);
      if (d1.getFullYear() !== y || d1.getMonth() !== mo || d1.getDate() !== dd) {
        throw Bad("日期不存在");
      }
      return { date: d1, rel: false };
    }

    /* 月-日：11-07 08:30（已过则顺延明年） */
    m = /^(\d{1,2})[-/.](\d{1,2})[ T]+(.+)$/.exec(s);
    if (m) {
      var mo2 = parseInt(m[1], 10) - 1;
      var dd2 = parseInt(m[2], 10);
      var t2 = parseTimePart(m[3].trim());
      if (!t2 || !validHM(t2[0], t2[1])) throw Bad();
      var year = nowD.getFullYear();
      var d2 = new Date(year, mo2, dd2, t2[0], t2[1], 0, 0);
      if (d2.getMonth() !== mo2 || d2.getDate() !== dd2) throw Bad("日期不存在");
      if (d2.getTime() <= nowD.getTime()) {
        d2 = new Date(year + 1, mo2, dd2, t2[0], t2[1], 0, 0);
      }
      return { date: d2, rel: false };
    }

    /* 纯时间 */
    var t = parseTimePart(s);
    if (!t || !validHM(t[0], t[1])) throw Bad();

    var out;
    if (dayOffset !== null) {
      var base = startOfDay(nowD);
      base.setDate(base.getDate() + dayOffset);
      out = new Date(base.getFullYear(), base.getMonth(), base.getDate(), t[0], t[1], 0, 0);
    } else {
      out = new Date(nowD.getFullYear(), nowD.getMonth(), nowD.getDate(), t[0], t[1], 0, 0);
      if (out.getTime() <= nowD.getTime()) out.setDate(out.getDate() + 1);
    }
    return { date: out, rel: false };
  }

  /* 14:35 / 明天 09:00 / 后天 09:00 / 11-07 08:30 / 2027-01-02 08:30 */
  function formatWhen(d, now) {
    var nowD = now ? new Date(now.getTime()) : new Date();
    var diff = Math.round((startOfDay(d).getTime() - startOfDay(nowD).getTime()) / DAY);
    var hm = pad(d.getHours()) + ":" + pad(d.getMinutes());
    if (diff === 0) return hm;
    if (diff === 1) return "明天 " + hm;
    if (diff === 2) return "后天 " + hm;
    if (d.getFullYear() === nowD.getFullYear()) {
      return pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " + hm;
    }
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " + hm;
  }

  /* 列表里更紧凑：14:35 / 明 09:00 / 后 09:00 / 11-07 08:30 */
  function formatRow(d, now) {
    var nowD = now ? new Date(now.getTime()) : new Date();
    var diff = Math.round((startOfDay(d).getTime() - startOfDay(nowD).getTime()) / DAY);
    var hm = pad(d.getHours()) + ":" + pad(d.getMinutes());
    if (diff === 0) return hm;
    if (diff === 1) return "明 " + hm;
    if (diff === 2) return "后 " + hm;
    if (d.getFullYear() === nowD.getFullYear()) {
      return pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " + hm;
    }
    return pad(d.getFullYear() % 100) + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  /* 2026-11-05T14:35（本地时间，Rust 侧按 %Y-%m-%dT%H:%M 解析） */
  function toIso(d) {
    return (
      d.getFullYear() +
      "-" +
      pad(d.getMonth() + 1) +
      "-" +
      pad(d.getDate()) +
      "T" +
      pad(d.getHours()) +
      ":" +
      pad(d.getMinutes())
    );
  }

  function fromIso(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(String(s));
    if (!m) return new Date(NaN);
    return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], 0, 0);
  }

  root.TTP = {
    parseTarget: parseTarget,
    formatWhen: formatWhen,
    formatRow: formatRow,
    toIso: toIso,
    fromIso: fromIso,
    pad: pad,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
