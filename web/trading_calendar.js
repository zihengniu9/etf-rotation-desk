/*
 * A股交易日历（前端）。
 * 只列工作日休市日，周末默认休市。来源：沪深北交易所《2026年部分节假日休市安排》。
 * 每年 12 月交易所公布次年安排后补充，并同步 scripts/build_dashboard_status.py 的 MARKET_HOLIDAYS；
 * tests/test_dashboard_status.py 会校验两边一致。未覆盖的年份只跳过周末，并通过 covered=false 提示。
 */
(function (scope) {
  "use strict";

  var HOLIDAYS = {
    // 元旦 1/1-1/3，春节 2/15-2/23，清明 4/4-4/6，劳动节 5/1-5/5，端午 6/19-6/21，中秋 9/25-9/27，国庆 10/1-10/7
    "2026": [
      "2026-01-01", "2026-01-02",
      "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-23",
      "2026-04-06",
      "2026-05-01", "2026-05-04", "2026-05-05",
      "2026-06-19",
      "2026-09-25",
      "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"
    ]
  };

  var closed = {};
  Object.keys(HOLIDAYS).forEach(function (year) {
    HOLIDAYS[year].forEach(function (day) { closed[day] = true; });
  });

  function pad(value) { return String(value).padStart(2, "0"); }
  function toIso(date) { return date.getUTCFullYear() + "-" + pad(date.getUTCMonth() + 1) + "-" + pad(date.getUTCDate()); }
  function fromIso(iso) {
    var text = String(iso).slice(0, 10), date = new Date(text + "T00:00:00Z");
    return /^\d{4}-\d{2}-\d{2}$/.test(text) && !isNaN(date.getTime()) && toIso(date) === text ? date : new Date(NaN);
  }

  function isCovered(iso) { return Object.prototype.hasOwnProperty.call(HOLIDAYS, String(iso).slice(0, 4)); }

  function isTradingDay(iso) {
    var date = fromIso(iso);
    if (isNaN(date.getTime())) return false;
    var day = date.getUTCDay();
    return day !== 0 && day !== 6 && !closed[String(iso).slice(0, 10)];
  }

  function nextTradingDay(iso) {
    var date = fromIso(iso);
    if (isNaN(date.getTime())) return { date: "", covered: false };
    var covered = isCovered(iso);
    do { date.setUTCDate(date.getUTCDate() + 1); covered = covered && isCovered(toIso(date)); } while (!isTradingDay(toIso(date)));
    var next = toIso(date);
    return { date: next, covered: covered };
  }

  scope.TRADING_CALENDAR = {
    holidays: HOLIDAYS,
    isTradingDay: isTradingDay,
    nextTradingDay: nextTradingDay,
    isCovered: isCovered
  };
})(typeof window !== "undefined" ? window : globalThis);
