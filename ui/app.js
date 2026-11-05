/* TodayTick · 主窗口逻辑 */
(function () {
  "use strict";

  var T = window.__TAURI__ || {};
  var invoke = (T.core && T.core.invoke) || function () {
    return Promise.reject(new Error("Tauri 未就绪"));
  };
  var listen = (T.event && T.event.listen) || function () {
    return Promise.resolve(function () {});
  };

  var P = window.TTP;
  var $ = function (id) {
    return document.getElementById(id);
  };

  var shell = $("shell");
  var list = $("list");
  var desc = $("desc");
  var when = $("when");
  var hint = $("hint");
  var section = $("section");

  var state = { items: [], autostart: false };
  var lastHeight = 0;
  var errTimer = null;
  var adding = false;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* ------------------------------------------------------------ 尺寸 */

  function syncHeight() {
    var h = Math.ceil(shell.getBoundingClientRect().height);
    if (h !== lastHeight) {
      lastHeight = h;
      invoke("resize_main", { height: h }).catch(function () {});
    }
  }

  /* ------------------------------------------------------------ 渲染 */

  function renderSection(err) {
    if (err) {
      section.classList.add("bad");
      section.textContent = err;
    } else {
      section.classList.remove("bad");
      section.innerHTML = '待提醒 <span class="count">' + state.items.length + "</span>";
    }
  }

  function render() {
    var now = new Date();
    var items = state.items.slice().sort(function (a, b) {
      return a.when < b.when ? -1 : a.when > b.when ? 1 : 0;
    });

    if (!items.length) {
      list.innerHTML =
        '<div class="empty"><p>暂时没有待办的提醒</p><p class="sub">写下来，到时间提醒你</p></div>';
    } else {
      list.innerHTML = items
        .map(function (it) {
          var d = P.fromIso(it.when);
          var overdue = d.getTime() <= now.getTime();
          return (
            '<div class="row' +
            (overdue ? " overdue" : "") +
            '" data-id="' +
            it.id +
            '">' +
            '<span class="t" title="' + esc(P.formatWhen(d, now)) + '">' +
            P.formatRow(d, now) +
            "</span>" +
            '<span class="txt" title="' + esc(it.text) + '">' +
            esc(it.text) +
            "</span>" +
            '<button class="del" data-del="' +
            it.id +
            '" title="删除" aria-label="删除提醒：' + esc(it.text) + '"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg></button>' +
            "</div>"
          );
        })
        .join("");
    }

    renderSection(null);
    requestAnimationFrame(syncHeight);
  }

  function renderToggles() {
    $("tgl-start").classList.toggle("on", !!state.autostart);
    $("tgl-start").setAttribute("aria-checked", String(!!state.autostart));
  }

  /* ------------------------------------------------------------ 数据 */

  function load() {
    return invoke("get_state")
      .then(function (s) {
        state = s;
        render();
        renderToggles();
      })
      .catch(function (e) {
        console.error(e);
        render();
        flashError("提醒读取失败，请重新打开窗口");
      });
  }

  /* ------------------------------------------------------------ 提示 */

  function updateHint() {
    var raw = when.value.trim();
    hint.className = "hint";
    when.removeAttribute("aria-invalid");
    requestAnimationFrame(syncHeight);
    if (!raw) {
      hint.textContent = "";
      return;
    }
    try {
      var parsed = P.parseTarget(raw, new Date());
      hint.textContent = P.formatWhen(parsed.date, new Date()) + " 提醒";
      hint.classList.add("ok");
    } catch (e) {
      hint.textContent = "时间没看懂";
      hint.classList.add("bad");
      when.setAttribute("aria-invalid", "true");
    }
  }

  function flashError(msg) {
    renderSection(msg);
    requestAnimationFrame(syncHeight);
    clearTimeout(errTimer);
    errTimer = setTimeout(function () {
      renderSection(null);
      requestAnimationFrame(syncHeight);
    }, 2600);
  }

  /* ------------------------------------------------------------ 添加 */

  function add() {
    if (adding) return;
    var text = desc.value.trim();
    var raw = when.value.trim();
    var parsed;
    try {
      parsed = P.parseTarget(raw, new Date());
    } catch (e) {
      flashError(e.message || "时间没看懂");
      when.setAttribute("aria-invalid", "true");
      when.focus();
      when.select();
      return;
    }
    if (!text) {
      flashError("先写一句要提醒的内容");
      desc.setAttribute("aria-invalid", "true");
      desc.focus();
      return;
    }
    adding = true;
    $("btn-add").disabled = true;
    invoke("add_reminder", { text: text, when: P.toIso(parsed.date) })
      .then(function () {
        desc.value = "";
        when.value = "";
        updateHint();
        desc.focus();
        return load();
      })
      .catch(function (e) {
        flashError(typeof e === "string" ? e : e.message || "添加失败");
      }).finally(function () {
        adding = false;
        $("btn-add").disabled = false;
      });
  }

  /* ------------------------------------------------------------ 事件 */

  desc.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.isComposing) {
      e.preventDefault();
      when.focus();
    }
  });

  desc.addEventListener("input", function () { desc.removeAttribute("aria-invalid"); });
  when.addEventListener("input", updateHint);
  when.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.isComposing) {
      e.preventDefault();
      add();
    }
  });

  $("btn-add").addEventListener("click", add);

  list.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-del]");
    if (!btn) return;
    invoke("remove_reminder", { id: Number(btn.dataset.del) })
      .then(load)
      .catch(function (err) {
        console.error(err);
        flashError("删除失败，请重试");
      });
  });

  $("tgl-start").addEventListener("click", function () {
    var want = !state.autostart;
    invoke("set_autostart", { on: want })
      .then(function (on) {
        state.autostart = !!on;
        renderToggles();
      })
      .catch(function (e) {
        flashError(typeof e === "string" ? e : "开机自启设置失败");
        renderToggles();
      });
  });

  $("btn-close").addEventListener("click", function () {
    invoke("hide_main").catch(function (e) {
      flashError(typeof e === "string" ? e : "托盘未就绪，窗口未隐藏");
    });
  });

  /* ------------------------------------------------------------ 时钟 */

  function tickClock() {
    var d = new Date();
    $("clock").textContent = P.pad(d.getHours()) + ":" + P.pad(d.getMinutes());
  }

  /* ------------------------------------------------------------ 启动 */

  function boot() {
    updateHint();
    tickClock();
    setInterval(tickClock, 1000);
    load();
    listen("state-changed", function () {
      load();
    });
    setInterval(function () {
      if (!document.querySelector(".row:hover, .row:focus-within")) render();
    }, 60000);
  }

  document.addEventListener("DOMContentLoaded", boot);
  window.addEventListener("load", syncHeight);
})();
