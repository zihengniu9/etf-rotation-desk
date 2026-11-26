(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var state = { data: null, key: "original", stock: null, query: "" };
  var LABEL = { original: "原策略", candidate: "新参数（观察中）" };
  var COLOR = { original: "#c82835", candidate: "#1d4ed8" };

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[c];
    });
  }
  function isNum(v) { return typeof v === "number" && isFinite(v); }
  function pct(v, digits, signed) {
    if (!isNum(v)) return "—";
    var s = v.toFixed(digits == null ? 1 : digits) + "%";
    return signed !== false && v > 0 ? "+" + s : s;
  }
  function cls(v) { return isNum(v) ? (v > 0 ? "up" : (v < 0 ? "down" : "")) : ""; }
  function money(v) {
    if (!isNum(v)) return "—";
    var a = Math.abs(v), s = a >= 10000 ? (a / 10000).toFixed(1) + "万" : a.toFixed(0);
    return (v > 0 ? "+" : (v < 0 ? "-" : "")) + s;
  }
  function daysBetween(a, b) { return Math.round((b - a) / 86400000); }

  function loadData() {
    var url = "../outputs/leader_dip.json?ts=" + Date.now();
    return fetch(url, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("leader_dip.json " + r.status);
      return r.json();
    }).catch(function (err) {
      if (window.LEADER_DIP_DATA) return window.LEADER_DIP_DATA;   // file:// 打开时的兜底
      throw err;
    });
  }

  function showFresh(text, error) {
    var el = $("ld-fresh");
    el.textContent = text;
    el.className = "alert show" + (error ? " error" : "");
  }

  function renderHeader(d) {
    var cov = d.coverage || {};
    $("ld-date").textContent = "数据日期 " + (d.data_as_of || "—");
    $("source-dot").className = "dot ready";
    $("ld-generated").textContent = "生成于 " + String(d.generated_at || "—").replace("T", " ").slice(0, 16);
    if (d.data_as_of) {
      var lag = daysBetween(new Date(d.data_as_of + "T00:00:00+08:00"), new Date());
      if (lag > 4) {
        showFresh("数据已经 " + lag + " 天没有更新（数据日期 " + d.data_as_of + "）。请在 Mac 上收盘后运行每日更新，再查看信号。", false);
        $("ld-date").className = "pill up";
      }
    }
    $("cov-scanned").textContent = isNum(cov.scanned) ? cov.scanned.toLocaleString() : "—";
    $("cov-universe").textContent = cov.universe || "沪深主板";
    $("cov-valid").textContent = isNum(cov.valid_history) ? cov.valid_history.toLocaleString() : "—";
    $("cov-valid-note").textContent = "≥" + (cov.min_history_days || 60) + " 个交易日 · 有日线 " + (cov.with_daily_file || "—");
    $("cov-today").textContent = isNum(cov.updated_today) ? cov.updated_today.toLocaleString() : "—";
    $("cov-today-note").textContent = (cov.data_as_of || "—") + " 当天有收盘价";
    $("cov-hot").textContent = isNum(cov.hot_ranked_on_last_day) ? cov.hot_ranked_on_last_day.toLocaleString() : "—";
    $("cov-hot-note").textContent = "缓存 " + (cov.hot_stocks_cached || "—") + " 只 · 自 " + (cov.hot_history_start || "—");
    var p = (d.periods || {})["全区间"] || [];
    $("cov-period").textContent = p.length ? p[0].slice(2) + " ~ " + p[1].slice(2) : "—";
    var full = ((d.strategies || {}).original || {}).periods;
    $("cov-days").textContent = full && full["全区间"] ? full["全区间"].trading_days : "—";
    var src = cov.sources || {};
    $("ld-source-text").innerHTML =
      "<strong>日线：</strong>" + esc(src.daily || "—") + "<br><strong>热度：</strong>" + esc(src.popularity || "—") +
      "<br><strong>名单：</strong>" + esc(src.universe || "—") + "<br><strong>说明：</strong>" + esc(cov.universe_note || "") +
      (src.is_wencai === false ? "。本模块不是同花顺问财数据，和项目其他问财模块口径不同。" : "");
  }

  function renderStrip(d) {
    var rows = (d.emotion || []).slice(-40);
    var svg = $("ld-strip");
    if (!rows.length) { svg.innerHTML = ""; return; }
    var max = Math.max.apply(null, rows.map(function (r) { return Math.max(r.limit_up || 0, r.limit_down || 0); })) || 1;
    var w = 600 / rows.length, mid = 45, scale = 40 / max, html = "";
    rows.forEach(function (r, i) {
      var x = i * w + w * 0.15, bw = w * 0.7;
      var hu = (r.limit_up || 0) * scale, hd = (r.limit_down || 0) * scale;
      html += '<rect x="' + x.toFixed(1) + '" y="' + (mid - hu).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + hu.toFixed(1) + '" fill="rgba(215,25,32,.55)"><title>' + esc(r.date) + " 涨停 " + r.limit_up + "</title></rect>";
      html += '<rect x="' + x.toFixed(1) + '" y="' + mid + '" width="' + bw.toFixed(1) + '" height="' + hd.toFixed(1) + '" fill="rgba(15,123,85,.55)"><title>' + esc(r.date) + " 跌停 " + r.limit_down + "</title></rect>";
      if (r.ice) html += '<circle cx="' + (x + bw / 2).toFixed(1) + '" cy="' + mid + '" r="3.2" fill="#1d4ed8"><title>' + esc(r.date) + " 冰点</title></circle>";
    });
    html += '<line x1="0" x2="600" y1="' + mid + '" y2="' + mid + '" stroke="#e6e8ee" stroke-width="1"/>';
    svg.innerHTML = html;
  }

  function renderSignal(d) {
    var st = (d.strategies || {})[state.key];
    if (!st) return;
    var s = st.signal || {};
    var box = $("ld-verdict-box");
    box.className = "decision" + (s.can_open_next_day ? "" : " hold");
    $("ld-verdict-for").textContent = "基于 " + (s.data_as_of || "—") + " 收盘 · 用于下一交易日";
    $("ld-verdict").textContent = s.can_open_next_day ? "可以开仓" : "不开仓";
    var why = s.can_open_next_day
      ? "近 " + s.ice_window + " 个交易日内出现过冰点，处在低吸窗口内。"
      : (s.retreat_blocked ? "退潮过滤触发。" : "近 " + s.ice_window + " 个交易日没有冰点，等待情绪冰点。");
    $("ld-verdict-why").textContent = why;
    $("emo-up").textContent = isNum(s.limit_up) ? s.limit_up : "—";
    $("emo-down").textContent = isNum(s.limit_down) ? s.limit_down : "—";
    $("emo-prem").innerHTML = '<span class="' + cls(s.prev_limit_up_premium_pct) + '">' + pct(s.prev_limit_up_premium_pct, 2) + "</span>";
    $("emo-boards").textContent = isNum(s.max_boards) ? s.max_boards + " 板" : "—";
    $("emo-ice").textContent = s.is_ice_today ? "是" : "否";
    var r = s.rules || {};
    $("ld-rule").textContent = "规则（" + LABEL[state.key] + "）：热度前 " + r.hot_topn + " 且高度 ≥" + r.height_min_pct +
      "%，按热度+高度综合排序；低吸挂单价 = 收盘价 × (1" + (r.dip_pct >= 0 ? "+" : "") + r.dip_pct + "%)；单票 " + r.pos_size_pct + "%，总仓位上限 " + r.max_pos_pct + "%。";
    var rows = (s.leaders || []).map(function (x) {
      var tips = [];
      if (isNum(x.hot_rank) && x.hot_rank <= 5) tips.push('<span class="tag watch">热度前5，历史表现偏弱</span>');
      if (isNum(x.dev10_pct) && x.dev10_pct >= 80) tips.push('<span class="tag risk">10日偏离接近100%</span>');
      if (isNum(x.dev30_pct) && x.dev30_pct >= 170) tips.push('<span class="tag risk">30日偏离接近200%</span>');
      if (isNum(x.height_pct) && x.height_pct > 120) tips.push('<span class="tag">高度超120%</span>');
      return '<tr><td><div class="stock"><span class="rank">' + x.rank + "</span><div><strong>" + esc(x.name) + "</strong><small>" + esc(x.code) + "</small></div></div></td>" +
        '<td class="num">' + (isNum(x.hot_rank) ? x.hot_rank : "—") + '</td><td class="num">' + pct(x.height_pct, 0, false) + "</td>" +
        '<td class="num ' + cls(x.pct) + '">' + pct(x.pct, 2) + '</td><td class="num">' + (isNum(x.close) ? x.close.toFixed(2) : "—") + "</td>" +
        '<td class="num"><strong>' + (isNum(x.dip_price) ? x.dip_price.toFixed(2) : "—") + "</strong></td>" +
        '<td class="num">' + pct(x.dev10_pct, 0) + '</td><td class="num">' + pct(x.dev30_pct, 0) + "</td><td>" + (tips.join(" ") || '<span class="muted">—</span>') + "</td></tr>";
    });
    $("ld-leaders").innerHTML = rows.length ? rows.join("") : '<tr><td colspan="9"><div class="empty">当前没有同时满足热度和高度条件的股票。</div></td></tr>';
  }

  function renderMetrics(d) {
    var st = d.strategies[state.key], p = st.periods["全区间"] || {};
    $("ld-bt-badge").textContent = LABEL[state.key] + " · " + (d.periods["全区间"] || []).join(" ~ ");
    var items = [
      ["全区间收益", pct(p.total_return_pct, 1), cls(p.total_return_pct), "年化 " + pct(p.annual_return_pct, 1)],
      ["最大回撤", pct(p.max_drawdown_pct, 1, false), "down", "平均仓位 " + pct(p.avg_position_pct, 0, false)],
      ["交易笔数", isNum(p.trades) ? p.trades : "—", "", "平均持有 " + (isNum(p.avg_hold_days) ? p.avg_hold_days.toFixed(1) : "—") + " 天"],
      ["胜率", pct(p.win_rate_pct, 0, false), "", "中位单笔 " + pct(p.median_trade_pct, 2)],
      ["单笔均值", pct(p.avg_trade_pct, 2), cls(p.avg_trade_pct), "盈 " + pct(p.avg_win_pct, 1) + " / 亏 " + pct(p.avg_loss_pct, 1)],
      ["去掉最赚3笔", money(p.pnl_ex_top3), cls(p.pnl_ex_top3), "利润是否依赖少数几笔"],
    ];
    $("ld-metrics").innerHTML = items.map(function (it) {
      return '<div class="stat"><span>' + it[0] + '</span><strong class="' + it[2] + '">' + it[1] + "</strong><small>" + esc(it[3]) + "</small></div>";
    }).join("");
  }

  function renderNav(d) {
    var series = ["original", "candidate"].map(function (k) { return { key: k, pts: (d.strategies[k] || {}).nav || [] }; })
      .filter(function (s) { return s.pts.length; });
    var svg = $("ld-nav");
    if (!series.length) { svg.innerHTML = ""; return; }
    var all = [];
    series.forEach(function (s) { s.pts.forEach(function (p) { all.push(p[1]); }); });
    var lo = Math.min.apply(null, all.concat([1])), hi = Math.max.apply(null, all.concat([1]));
    var pad = (hi - lo) * 0.08 || 0.05; lo -= pad; hi += pad;
    var W = 900, H = 260, L = 46, B = 22, T = 8;
    var y = function (v) { return T + (H - T - B) * (1 - (v - lo) / (hi - lo)); };
    var n = series[0].pts.length;
    var x = function (i) { return L + (W - L - 8) * (i / Math.max(n - 1, 1)); };
    var html = "";
    for (var g = 0; g <= 4; g++) {
      var v = lo + (hi - lo) * g / 4;
      html += '<line x1="' + L + '" x2="' + W + '" y1="' + y(v).toFixed(1) + '" y2="' + y(v).toFixed(1) + '" stroke="#eef0f4"/>' +
        '<text x="' + (L - 6) + '" y="' + (y(v) + 4).toFixed(1) + '" text-anchor="end" font-size="11" fill="#747b87">' + v.toFixed(2) + "</text>";
    }
    html += '<line x1="' + L + '" x2="' + W + '" y1="' + y(1).toFixed(1) + '" y2="' + y(1).toFixed(1) + '" stroke="#c7ccd6" stroke-dasharray="4 4"/>';
    [0, Math.floor((n - 1) / 2), n - 1].forEach(function (i) {
      var lab = series[0].pts[i][0];
      html += '<text x="' + x(i).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="' + (i === 0 ? "start" : (i === n - 1 ? "end" : "middle")) + '" font-size="11" fill="#747b87">' + esc(lab) + "</text>";
    });
    series.forEach(function (s) {
      var path = s.pts.map(function (p, i) { return (i ? "L" : "M") + x(i).toFixed(1) + " " + y(p[1]).toFixed(1); }).join(" ");
      var last = s.pts[s.pts.length - 1];
      html += '<path d="' + path + '" fill="none" stroke="' + COLOR[s.key] + '" stroke-width="' + (s.key === state.key ? 2.6 : 1.6) + '" opacity="' + (s.key === state.key ? 1 : 0.6) + '"/>' +
        '<text x="' + (W - 10) + '" y="' + (y(last[1]) - 6).toFixed(1) + '" text-anchor="end" font-size="12" font-weight="700" fill="' + COLOR[s.key] + '">' + last[1].toFixed(3) + "</text>";
    });
    svg.innerHTML = html;
  }

  function periodRows(d) {
    var html = "";
    ["original", "candidate"].forEach(function (k) {
      var st = d.strategies[k]; if (!st) return;
      ["全区间", "前半段", "后半段"].forEach(function (pn, i) {
        var p = st.periods[pn] || {};
        var range = (d.periods[pn] || []).map(function (s) { return s.slice(2); }).join("~");
        html += "<tr" + (k === state.key ? ' class="selected"' : "") + "><td>" + (i === 0 ? "<strong>" + esc(LABEL[k]) + "</strong>" : "") + "</td>" +
          "<td>" + esc(pn) + ' <small style="color:var(--muted)">' + esc(range) + "</small></td>" +
          '<td class="num ' + cls(p.total_return_pct) + '">' + pct(p.total_return_pct, 1) + '</td><td class="num">' + pct(p.max_drawdown_pct, 1, false) + "</td>" +
          '<td class="num">' + (isNum(p.trades) ? p.trades : "—") + '</td><td class="num">' + pct(p.win_rate_pct, 0, false) + "</td>" +
          '<td class="num ' + cls(p.avg_trade_pct) + '">' + pct(p.avg_trade_pct, 2) + '</td><td class="num ' + cls(p.pnl_ex_top3) + '">' + money(p.pnl_ex_top3) + "</td></tr>";
      });
    });
    $("ld-periods").innerHTML = html;
    var reasons = d.strategies[state.key].exit_reasons || [];
    $("ld-reasons").innerHTML = reasons.length ? reasons.map(function (r) {
      return "<tr><td>" + esc(r.reason) + '</td><td class="num">' + r.count + '</td><td class="num ' + cls(r.avg_return_pct) + '">' + pct(r.avg_return_pct, 2) + "</td></tr>";
    }).join("") : '<tr><td colspan="3"><div class="empty">暂无交易</div></td></tr>';
  }

  function compareRow(label, row, extra) {
    var a = row["全区间"] || {}, f = row["前半段"] || {}, s = row["后半段"] || {};
    return "<tr><td>" + esc(label) + '</td><td class="num ' + cls(a.total_return_pct) + '">' + pct(a.total_return_pct, 1) + "</td>" +
      '<td class="num ' + cls(f.total_return_pct) + '">' + pct(f.total_return_pct, 1) + '</td><td class="num ' + cls(s.total_return_pct) + '">' + pct(s.total_return_pct, 1) + "</td>" +
      '<td class="num">' + pct(a.max_drawdown_pct, 1, false) + '</td><td class="num">' + (isNum(a.trades) ? a.trades : "—") + '</td><td class="num">' + pct(a.win_rate_pct, 0, false) + "</td>" + extra + "</tr>";
  }

  function renderTables(d) {
    $("ld-sizing-label").textContent = LABEL[state.key];
    $("ld-sizing").innerHTML = ((d.sizing || {})[state.key] || []).map(function (r) {
      var a = r["全区间"] || {};
      return compareRow(r.label, r, '<td class="num ' + cls(a.pnl_ex_top3) + '">' + money(a.pnl_ex_top3) + "</td>");
    }).join("");
    var variants = d.variants || [];
    $("ld-variants").innerHTML = variants.map(function (r, i) {
      var tag = i === 0 ? '<span class="tag">基准</span>'
        : (r.beats_baseline_both_halves ? '<span class="tag primary">两段都更好</span>' : '<span class="tag">未稳定胜出</span>');
      return compareRow(r.label, r, "<td>" + tag + "</td>");
    }).join("");
  }

  function renderTrades(d) {
    var st = d.strategies[state.key];
    var q = state.query.trim().toLowerCase();
    var match = function (x) { return !q || String(x.code).indexOf(q) >= 0 || String(x.name).toLowerCase().indexOf(q) >= 0; };
    var effects = (st.stock_effects || []).filter(match);
    $("ld-tr-badge").textContent = LABEL[state.key] + " · " + (st.trades || []).length + " 笔 · " + (st.stock_effects || []).length + " 只";
    $("ld-effects").innerHTML = effects.length ? effects.map(function (e) {
      return '<tr class="clickable' + (state.stock === e.code ? " selected" : "") + '" data-code="' + esc(e.code) + '" tabindex="0">' +
        '<td><div class="stock"><div><strong>' + esc(e.name) + "</strong><small>" + esc(e.code) + " · 最近 " + esc(e.last_buy) + "</small></div></div></td>" +
        '<td class="num">' + e.signals + '</td><td class="num">' + pct(e.win_rate_pct, 0, false) + "</td>" +
        '<td class="num ' + cls(e.avg_return_pct) + '">' + pct(e.avg_return_pct, 2) + '</td><td class="num ' + cls(e.median_return_pct) + '">' + pct(e.median_return_pct, 2) + "</td>" +
        '<td class="num"><span class="up">' + pct(e.best_pct, 1) + '</span> / <span class="down">' + pct(e.worst_pct, 1) + "</span></td>" +
        '<td class="num ' + cls(e.pnl) + '">' + money(e.pnl) + "</td></tr>";
    }).join("") : '<tr><td colspan="7"><div class="empty">没有匹配的股票</div></td></tr>';
    var trades = (st.trades || []).filter(function (t) { return (!state.stock || t.code === state.stock) && match(t); }).slice().reverse();
    $("ld-trades").innerHTML = trades.length ? trades.map(function (t) {
      return '<tr><td><div class="stock"><div><strong>' + esc(t.name) + "</strong><small>" + esc(t.code) + "</small></div></div></td><td>" + esc(t.buy_date) + "</td><td>" + esc(t.sell_date) + "</td>" +
        '<td class="num">' + t.hold_days + '</td><td class="num">' + (isNum(t.hot_rank) ? t.hot_rank : "—") + '</td><td class="num">' + pct(t.height_pct, 0, false) + "</td>" +
        '<td class="num ' + cls(t.return_pct) + '"><strong>' + pct(t.return_pct, 2) + "</strong></td><td>" + esc(t.exit_reason) + "</td>" +
        '<td class="num">' + pct(t.after_exit_max_pct, 1) + "</td></tr>";
    }).join("") : '<tr><td colspan="9"><div class="empty">没有匹配的交易</div></td></tr>';
    $("ld-filter-note").textContent = state.stock ? "已筛选：" + state.stock + "（再点一次或点“清除筛选”取消）" : "点击左侧个股可筛选交易明细。";
  }

  function renderAll() {
    var d = state.data;
    renderSignal(d); renderMetrics(d); renderNav(d); periodRows(d); renderTables(d); renderTrades(d);
  }

  function bind() {
    Array.prototype.forEach.call(document.querySelectorAll("#ld-seg button"), function (btn) {
      btn.addEventListener("click", function () {
        state.key = btn.getAttribute("data-key");
        Array.prototype.forEach.call(document.querySelectorAll("#ld-seg button"), function (b) {
          var on = b === btn; b.classList.toggle("active", on); b.setAttribute("aria-selected", on ? "true" : "false");
        });
        state.stock = null;
        renderAll();
      });
    });
    $("ld-search").addEventListener("input", function (e) { state.query = e.target.value; renderTrades(state.data); });
    $("ld-clear").addEventListener("click", function () { state.stock = null; state.query = ""; $("ld-search").value = ""; renderTrades(state.data); });
    var pick = function (e) {
      var tr = e.target.closest("tr[data-code]");
      if (!tr) return;
      if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
      if (e.type === "keydown") e.preventDefault();
      var code = tr.getAttribute("data-code");
      state.stock = state.stock === code ? null : code;
      renderTrades(state.data);
    };
    $("ld-effects").addEventListener("click", pick);
    $("ld-effects").addEventListener("keydown", pick);
  }

  function start() {
    loadData().then(function (d) {
      if (!d || d.version !== "leader-dip-v1" || !d.strategies || !d.strategies.original) {
        throw new Error("数据格式不符合 leader-dip-v1");
      }
      state.data = d;
      renderHeader(d);
      renderStrip(d);
      $("ld-assume").innerHTML = (d.assumptions || []).concat([d.disclaimer || ""]).filter(Boolean)
        .map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("");
      bind();
      renderAll();
    }).catch(function (err) {
      showFresh("龙头低吸数据未接入：" + err.message + "。需要先在 Mac 上运行 scripts/build_leader_dip.py 生成 outputs/leader_dip.json。", true);
      $("ld-leaders").innerHTML = '<tr><td colspan="9"><div class="empty">数据缺失，不显示信号。</div></td></tr>';
      $("ld-verdict").textContent = "数据缺失";
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
