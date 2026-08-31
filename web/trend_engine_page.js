(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var state = { data: null, selected: 0 };
  var num = function (value, fallback) {
    var n = Number(value);
    return Number.isFinite(n) ? n : (fallback || 0);
  };
  var escapeHtml = function (value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return ({"&":"&amp;", "<":"&lt;", ">":"&gt;", "\"":"&quot;", "'":"&#39;"})[c];
    });
  };
  var percent = function (value, digits) {
    var n = num(value) * 100;
    return (n >= 0 ? "+" : "") + n.toFixed(digits == null ? 1 : digits) + "%";
  };
  var ratio = function (value, digits) {
    var n = num(value) * 100;
    return n.toFixed(digits == null ? 1 : digits) + "%";
  };
  var returnClass = function (value) { return num(value) > 0 ? "up" : (num(value) < 0 ? "down" : ""); };

  function fetchJson(path) {
    return fetch(path + "?ts=" + Date.now(), { cache: "no-store" }).then(function (response) {
      if (!response.ok) throw new Error(path + " " + response.status);
      return response.json();
    });
  }

  function setEngineStatus(kind, label) {
    $("engine-status").className = "engine-status " + (kind || "");
    $("engine-status").textContent = label;
    $("source-dot").className = "dot " + (kind === "ready" ? "success" : (kind === "error" ? "danger" : ""));
  }

  function profitItem(effect, horizon) {
    var item = effect && effect.horizons && effect.horizons[horizon];
    return item && item.count ? item : null;
  }

  function profitHtml(effect, horizon) {
    var item = profitItem(effect, horizon);
    if (!item || item.avg_return == null) return '<span class="profit-na">待样本</span>';
    var cls = returnClass(item.avg_return);
    var mae = item.max_adverse == null ? "" : " · MAE " + percent(item.max_adverse, 1);
    return '<div class="profit ' + cls + '"><strong>' + escapeHtml(percent(item.avg_return, 1)) + '</strong><small>胜率 ' + escapeHtml((num(item.win_rate) * 100).toFixed(0)) + '% · n=' + item.count + escapeHtml(mae) + '</small></div>';
  }

  function renderStats(data) {
    var universe = data.universe || {};
    var decision = data.decision || {};
    var gate = decision.gate || {};
    var gated = data.gated_strategies || {};
    var contract = data.trend_contract || {};
    var selectedStrategy = contract.selected_strategy || "健康延续";
    var selectedItem = profitItem(gated[selectedStrategy], String(contract.selected_horizon || 10));
    var continuationTen = profitItem(gated["健康延续"], "10");
    var pullbackTen = profitItem(gated["缩量回踩"], "10");
    var preferred = selectedItem || (continuationTen && pullbackTen
      ? (num(continuationTen.avg_return) >= num(pullbackTen.avg_return) ? continuationTen : pullbackTen)
      : (continuationTen || pullbackTen));
    $("stocks-scanned").textContent = universe.stocks_scanned == null ? "—" : universe.stocks_scanned;
    $("trend-breadth").textContent = gate.eligible_ratio == null ? "—" : ratio(gate.eligible_ratio, 1);
    $("trend-count").textContent = gate.eligible_count == null ? "达到结构门槛" : gate.eligible_count + " 只达到结构门槛";
    $("positive-r20").textContent = gate.positive_r20_ratio == null ? "—" : ratio(gate.positive_r20_ratio, 1);
    $("candidate-count").textContent = (data.candidates || []).length;
    $("signal-count").textContent = (continuationTen ? continuationTen.count : 0) + (pullbackTen ? pullbackTen.count : 0) || "—";
    $("profit-label").textContent = preferred && preferred.avg_return != null ? percent(preferred.avg_return, 1) : "—";
    $("mode-label").textContent = decision.mode || "等待判定";
    $("action-label").textContent = decision.action || "等待全主板数据";
    $("mode-reason").textContent = decision.reason || "市场门控先于个股排名。";
    $("gate-rule").textContent = "趋势宽度 ≥ " + ratio(gate.eligible_ratio_min == null ? 0.08 : gate.eligible_ratio_min, 0) + " · 近20日上涨占比 ≥ " + ratio(gate.positive_r20_ratio_min == null ? 0.50 : gate.positive_r20_ratio_min, 0);
    var anchor = document.querySelector(".anchor");
    if (anchor) anchor.dataset.tone = decision.tone || "warning";
    $("scope-board").textContent = universe.board || "mainboard";
    $("scope-status").textContent = data.history_available ? ((data.config && data.config.history_dates ? data.config.history_dates.length : "—") + "期已加载") : "无完整历史";
    $("data-date").textContent = "数据日期 " + (data.data_as_of || "—");
    $("source-label").textContent = data.source || "本地趋势数据";
    $("table-note").textContent = decision.allow_new_entries
      ? "市场门控已开启。标准回测优先使用" + selectedStrategy + "，信号收盘确认，下一交易日开盘入场；缩量回踩作为次选。"
      : "当前市场门控关闭：以下股票全部仅作观察，不产生趋势新开仓。历史收益按下一交易日开盘入场统计。";
    $("profit-label").title = preferred && preferred.avg_return != null
      ? "门控开启时，" + selectedStrategy + "的" + (contract.selected_horizon || 10) + "日平均收益 " + percent(preferred.avg_return, 1) + "；未计费用"
      : "10日样本不足";
  }

  function renderStrategyCards(strategies, contract) {
    var container = $("strategy-grid");
    var selectedStrategy = (contract && contract.selected_strategy) || "健康延续";
    var definitions = [
      { name: "健康延续", badge: selectedStrategy === "健康延续" ? "标准回测优胜" : "收益候选", note: selectedStrategy === "健康延续" ? "当前标准回测综合质量最高，作为默认趋势触发；控制MA20乖离。" : "保留为收益候选，只有标准回测重新胜出才切换默认。" },
      { name: "缩量回踩", badge: selectedStrategy === "缩量回踩" ? "标准回测优胜" : "次选", note: selectedStrategy === "缩量回踩" ? "当前标准回测综合质量最高，作为默认趋势触发。" : "平均不利波动和正收益截面表现较稳，作为健康延续之外的次选。" },
      { name: "放量突破", badge: "非默认", note: "全样本稳定性较弱，暂不把追突破作为默认交易触发。" }
    ];
    container.innerHTML = definitions.map(function (definition) {
      var effect = strategies && strategies[definition.name];
      var item = profitItem(effect, "10");
      if (!item) return '<article class="strategy-card"><div class="empty">' + escapeHtml(definition.name) + '：样本不足</div></article>';
      return '<article class="strategy-card"><div class="strategy-card-head"><div><h3>' + escapeHtml(definition.name) + '</h3><small>固定观察 10 个交易日</small></div><span class="tag ' + (definition.name === "放量突破" ? "pending" : "watch") + '">' + escapeHtml(definition.badge) + '</span></div>' +
        '<div class="strategy-return"><strong class="' + returnClass(item.avg_return) + '">' + escapeHtml(percent(item.avg_return, 1)) + '</strong><span>样本平均收益</span></div>' +
        '<div class="strategy-metrics">' +
        '<div class="strategy-metric"><span>中位收益</span><strong>' + escapeHtml(percent(item.median_return, 1)) + '</strong></div>' +
        '<div class="strategy-metric"><span>个股胜率</span><strong>' + escapeHtml(ratio(item.win_rate, 0)) + '</strong></div>' +
        '<div class="strategy-metric"><span>正收益截面</span><strong>' + escapeHtml(ratio(item.positive_date_rate, 0)) + '</strong></div>' +
        '<div class="strategy-metric"><span>盈亏因子</span><strong>' + escapeHtml(item.profit_factor == null ? "—" : num(item.profit_factor).toFixed(2)) + '</strong></div>' +
        '<div class="strategy-metric"><span>平均不利波动</span><strong>' + escapeHtml(item.avg_adverse == null ? "—" : percent(item.avg_adverse, 1)) + '</strong></div>' +
        '<div class="strategy-metric"><span>样本</span><strong>' + escapeHtml(item.count + " / " + (item.date_count || 0) + "期") + '</strong></div></div>' +
        '<p class="strategy-note">' + escapeHtml(definition.note) + '</p></article>';
    }).join("");
  }

  function renderCandidates(candidates) {
    var body = $("candidate-body");
    if (!candidates.length) {
      body.innerHTML = '<tr><td colspan="7"><div class="empty">当前没有可展示的全主板趋势候选。请先生成 `outputs/trend_engine.json`，并确认其 universe.board 为 `mainboard`。</div></td></tr>';
      $("detail-panel").innerHTML = '<div class="empty">没有可选个股。当前页面只接受沪深主板全市场趋势数据。</div>';
      return;
    }
    body.innerHTML = candidates.map(function (candidate, index) {
      var effect = candidate.profit_effect || {};
      var gateOpen = !!(state.data && state.data.decision && state.data.decision.allow_new_entries);
      var tag = gateOpen ? (candidate.setup === "breakout" ? "突破" : (candidate.setup === "pullback" ? "回踩" : (candidate.setup === "continuation" ? "延续" : "观察"))) : "仅观察";
      var tone = gateOpen ? (candidate.setup === "continuation" ? "ready" : (candidate.setup === "pullback" ? "watch" : "pending")) : "pending";
      var selected = index === state.selected ? " selected-row" : "";
      return '<tr class="' + selected + '"><td><button class="stock-button" type="button" data-index="' + index + '"><div class="stock-name"><span class="rank">' + (index + 1) + '</span><div><strong>' + escapeHtml(candidate.name || candidate.code) + '</strong><small>' + escapeHtml(candidate.code || "—") + ' · ' + escapeHtml(candidate.theme || "—") + '</small></div></div></button></td>' +
        '<td><span class="tag ' + tone + '">' + tag + '</span></td>' +
        '<td><div class="score"><i style="--score:' + num(candidate.trend_score) + '%"></i><strong>' + num(candidate.trend_score).toFixed(0) + '</strong></div></td>' +
        '<td>' + profitHtml(effect, "5") + '</td><td>' + profitHtml(effect, "10") + '</td><td>' + profitHtml(effect, "20") + '</td>' +
        '<td>' + escapeHtml(effect.signals ? "信号 " + effect.signals + " · 评估 " + (effect.evaluated || 0) : "待样本") + '</td></tr>';
    }).join("");
    Array.prototype.forEach.call(body.querySelectorAll(".stock-button"), function (button) {
      button.addEventListener("click", function () {
        state.selected = Number(button.dataset.index) || 0;
        renderCandidates(candidates);
        renderDetail(candidates[state.selected]);
      });
    });
    renderDetail(candidates[state.selected]);
  }

  function detailFactor(label, value) {
    return '<div class="detail-factor"><span>' + escapeHtml(label) + '</span><strong>' + escapeHtml(value) + '</strong></div>';
  }

  function renderDetail(candidate) {
    if (!candidate) return;
    var effect = candidate.profit_effect || {};
    var decision = (state.data && state.data.decision) || {};
    var gateOpen = !!decision.allow_new_entries;
    var tag = gateOpen ? (candidate.setup === "breakout" ? "突破触发" : (candidate.setup === "pullback" ? "回踩触发" : (candidate.setup === "continuation" ? "延续触发" : "观察"))) : "门控关闭";
    var setup = candidate.setup === "breakout" ? "突破" : (candidate.setup === "pullback" ? "回踩" : (candidate.setup === "continuation" ? "健康延续" : "趋势观察"));
    $("detail-panel").innerHTML = '<div class="detail-title"><div><h3>' + escapeHtml(candidate.name || candidate.code) + '</h3><p>' + escapeHtml(candidate.code || "—") + ' · ' + escapeHtml(candidate.theme || "—") + ' · ' + setup + '</p></div><div><span class="tag ' + (gateOpen ? "watch" : "pending") + '">' + tag + '</span><div class="detail-score">' + num(candidate.trend_score).toFixed(0) + '</div></div></div>' +
      '<div class="detail-factors">' +
      detailFactor("20日收益", percent(candidate.r20, 1)) + detailFactor("60日收益", percent(candidate.r60, 1)) + detailFactor("120日收益", candidate.r120 == null ? "—" : percent(candidate.r120, 1)) +
      detailFactor("成交量比", candidate.volume_ratio == null ? "—" : num(candidate.volume_ratio).toFixed(2) + "×") + detailFactor("突破距离", candidate.breakout_distance == null ? "—" : percent(candidate.breakout_distance, 1)) + detailFactor("历史信号", effect.signals == null ? "—" : String(effect.signals)) +
      '</div><p class="detail-note">' + escapeHtml(candidate.note || "趋势结构待确认") + '。' + escapeHtml(decision.action || "趋势分只用于主板横截面研究") + '；个股历史效果不替代当前市场门控。</p>' +
      '<div class="detail-profit">' + detailProfitBox("5日后", effect, "5") + detailProfitBox("10日后", effect, "10") + detailProfitBox("20日后", effect, "20") + '</div>';
  }

  function detailProfitBox(label, effect, horizon) {
    var item = profitItem(effect, horizon);
    if (!item || item.avg_return == null) return '<div class="profit-box"><span>' + label + '</span><strong class="profit-na">待样本</strong><small>需要满足评估窗口的历史信号</small></div>';
    var pf = item.profit_factor == null ? "" : " · PF " + num(item.profit_factor).toFixed(2);
    return '<div class="profit-box"><span>' + label + '</span><strong class="' + returnClass(item.avg_return) + '">' + escapeHtml(percent(item.avg_return, 1)) + '</strong><small>胜率 ' + escapeHtml((num(item.win_rate) * 100).toFixed(0)) + '% · n=' + item.count + pf + '</small></div>';
  }

  function renderEmpty(message) {
    setEngineStatus("error", "未接入全主板日线");
    $("scope-status").textContent = "待生成";
    $("source-label").textContent = "未加载趋势数据";
    $("table-note").textContent = message;
    $("mode-label").textContent = "无法判定";
    $("action-label").textContent = "等待有效数据";
    $("mode-reason").textContent = message;
    $("candidate-body").innerHTML = '<tr><td colspan="7"><div class="empty">' + escapeHtml(message) + '</div></td></tr>';
    $("detail-panel").innerHTML = '<div class="empty">趋势因子页只接受沪深主板全市场数据，不使用短线梯队代理。</div>';
  }

  function render(data) {
    if (!data || !data.universe || data.universe.board !== "mainboard") {
      renderEmpty("趋势数据范围不是沪深主板，已停止展示候选。请使用更新后的主板数据生成脚本。");
      return;
    }
    state.data = data;
    var kind = data.history_available ? "ready" : "";
    setEngineStatus(kind, data.history_available ? "主板数据已加载" : "主板数据不完整");
    renderStats(data);
    renderStrategyCards(data.gated_strategies || {}, data.trend_contract || {});
    renderCandidates((data.candidates || []).slice().sort(function (a, b) { return num(b.trend_score) - num(a.trend_score); }));
  }

  function load() {
    $("refresh").disabled = true;
    fetchJson("../outputs/trend_engine.json").then(render).catch(function () {
      renderEmpty("未找到 outputs/trend_engine.json。请先准备全沪深主板日线CSV，再运行 update_trend_data.py。");
    }).finally(function () { $("refresh").disabled = false; });
  }

  $("refresh").addEventListener("click", load);
  load();
})();
