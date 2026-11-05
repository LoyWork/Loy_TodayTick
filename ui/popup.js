/* TodayTick · 弹窗逻辑 */
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

  var current = null;

  function syncSize() {
    var h = Math.ceil($("pcard").getBoundingClientRect().height) + 8;
    invoke("popup_ready", { height: h }).catch(function () {});
  }

  function refresh() {
    return invoke("current_popup")
      .then(function (item) {
        if (!item) return;
        current = item;
        var d = P.fromIso(item.when);
        $("ptime").textContent = P.formatWhen(d, new Date());
        $("ptext").textContent = item.text;
        $("pflag").hidden = !(Date.now() - d.getTime() > 60000);
        requestAnimationFrame(syncSize);
      })
      .catch(function (e) {
        console.error(e);
      });
  }

  function ack() {
    if (!current) return;
    invoke("ack_popup", { id: current.id }).catch(function (e) {
      console.error(e);
    });
  }

  function snooze() {
    if (!current) return;
    invoke("snooze_popup", { id: current.id, minutes: 5 }).catch(function (e) {
      console.error(e);
    });
  }

  $("ack").addEventListener("click", ack);
  $("snooze").addEventListener("click", snooze);

  document.addEventListener("keydown", function (e) {
    if (e.isComposing) return;
    if (e.key === "Enter" && document.activeElement.tagName !== "BUTTON") {
      e.preventDefault();
      ack();
    } else if (e.key === "Escape") {
      e.preventDefault();
      snooze();
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    refresh();
    listen("popup-refresh", refresh);
    window.addEventListener("resize", syncSize);
  });
})();
