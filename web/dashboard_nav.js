(function () {
  "use strict";

  var items = [
    { key: "market", label: "行情模式", href: "./market_mode.html" },
    { key: "etf", label: "ETF轮动", href: "./index.html" },
    { key: "industry", label: "行业主线", href: "./industry_mainline_dashboard.html" },
    { key: "short", label: "短线观察", href: "./shortterm_dashboard.html" },
    { key: "trend", label: "趋势因子", href: "./trend_engine.html" },
    { key: "growth", label: "成长因子", href: "./growth_factor.html" },
    { key: "dividend", label: "红利因子", href: "./dividend_factor.html" },
    { key: "short-factor", label: "短线因子", href: "./shortterm_factor_preview.html" },
    { key: "review", label: "每日复盘", href: "./market_mode.html#daily-review" },
  ];

  function activeKey() {
    var file = (window.location.pathname.split("/").pop() || "market_mode.html").toLowerCase();
    if ((file === "market_mode.html" || file === "market_overview.html") && window.location.hash === "#daily-review") return "review";
    if (file === "index.html" || file === "etf_rotation.html") return "etf";
    if (file === "industry_mainline_dashboard.html") return "industry";
    if (file === "shortterm_dashboard.html") return "short";
    if (file === "trend_engine.html") return "trend";
    if (file === "growth_factor.html") return "growth";
    if (file === "dividend_factor.html") return "dividend";
    if (file === "shortterm_factor_preview.html") return "short-factor";
    return "market";
  }

  function render() {
    var current = activeKey();
    Array.prototype.forEach.call(document.querySelectorAll(".dashboard-tabs"), function (nav) {
      nav.setAttribute("aria-label", "统一看板导航");
      nav.innerHTML = items.map(function (item) {
        var active = item.key === current;
        return '<a class="dashboard-tab' + (active ? ' active' : '') + '" href="' + item.href + '"' +
          (active ? ' aria-current="page"' : '') + '>' + item.label + '</a>';
      }).join("");
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", render);
  else render();
  window.addEventListener("hashchange", render);
})();
