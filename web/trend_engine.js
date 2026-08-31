(function (global) {
  "use strict";

  var clamp = function (value, low, high) {
    return Math.max(low, Math.min(high, value));
  };
  var num = function (value, fallback) {
    var parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : (fallback || 0);
  };
  var text = function (value) {
    return String(value == null ? "" : value);
  };
  var percent = function (value, digits) {
    var n = num(value);
    return (n >= 0 ? "+" : "") + n.toFixed(digits == null ? 1 : digits) + "%";
  };

  function normalize(value, low, high) {
    if (high === low) return 0;
    return clamp((num(value) - low) / (high - low) * 100, 0, 100);
  }

  function marketGate(snapshot) {
    var short = snapshot.short || {};
    var industry = snapshot.industry || {};
    var breadth = clamp(num(industry.breadth), 0, 100);
    var ratio = Math.max(0, num(industry.ratio));
    var excess = num(industry.return1d) - num(industry.benchmark1d);
    var score = clamp(
      num(short.score) * 0.35 +
      breadth * 0.25 +
      normalize(ratio, 0, 1.5) * 0.25 +
      normalize(excess, -1, 2) * 0.15,
      0,
      100
    );
    var blockers = [];
    if (num(short.score) < 60) blockers.push("短线市场评分低于60");
    if (num(short.limitDown) > 20) blockers.push("跌停家数重新扩张");
    if (num(short.failedRate) > 0.35) blockers.push("炸板率高于35%");
    if (breadth < 35) blockers.push("行业上涨扩散不足35%");
    if (ratio < 0.8) blockers.push("行业成交放量不足");

    return {
      score: Math.round(score),
      breadth: breadth,
      ratio: ratio,
      excess: excess,
      blockers: blockers
    };
  }

  function candidateScore(candidate) {
    var boards = num(candidate.boards || candidate.board_count);
    var pop = num(candidate.pop || candidate.pop_auction || candidate.popularity);
    var gap = num(candidate.gap);
    var closePct = candidate.close_pct != null ? num(candidate.close_pct) : (
      candidate.r20 != null ? num(candidate.r20) * 100 : num(candidate.pct || candidate.change)
    );
    var firstBreak = candidate.first_break === true || text(candidate.first_break).toLowerCase() === "true";
    var prevSealed = candidate.prev_sealed === true || text(candidate.prev_sealed).toLowerCase() === "true";
    var pullback = candidate.pullback === true || text(candidate.pullback).toLowerCase() === "true";
    var note = text(candidate.note);
    var rawSuppliedScore = Number(candidate.trend_score);
    var suppliedScore = Number.isFinite(rawSuppliedScore) ? rawSuppliedScore : NaN;
    var structure = clamp(boards * 12 + (prevSealed ? 18 : 0) + (firstBreak ? 22 : 0), 0, 45);
    var price = clamp(normalize(closePct, -5, 10), 0, 20);
    var attention = clamp(normalize(pop, 0, 100), 0, 15);
    var gapQuality = gap >= 0 && gap <= 6 ? 10 : (gap > 6 ? 3 : 0);
    var penalty = /低开走弱|一字|难上车|放弃/.test(note) ? 18 : 0;
    return {
      score: Number.isFinite(suppliedScore) ? Math.round(clamp(suppliedScore, 0, 100)) : Math.round(clamp(structure + price + attention + gapQuality - penalty, 0, 100)),
      firstBreak: firstBreak,
      prevSealed: prevSealed,
      pullback: pullback,
      closePct: closePct,
      pop: pop,
      gap: gap,
      note: note
    };
  }

  function candidateState(candidate, scored, historyAvailable, allowEntries) {
    if (/低开走弱|放弃/.test(scored.note)) return { label: "否决", tone: "blocked" };
    if (/一字|难上车/.test(scored.note)) return { label: "不追", tone: "blocked" };
    if (!historyAvailable) return { label: "待接入日线", tone: "pending" };
    if (!allowEntries) return { label: "仅观察", tone: "pending" };
    if (scored.firstBreak) return { label: "突破触发", tone: "ready" };
    if (scored.pullback) return { label: "回踩触发", tone: "watch" };
    if (text(candidate.setup) === "continuation") return { label: "延续触发", tone: "watch" };
    if (scored.prevSealed) return { label: "趋势延续", tone: "watch" };
    return { label: "等待确认", tone: "pending" };
  }

  function buildCandidates(snapshot) {
    var trend = snapshot.trend || {};
    var source = Array.isArray(trend.candidates) ? trend.candidates : [];
    var historyAvailable = trend.historyAvailable === true;
    var allowEntries = !(trend.decision && trend.decision.allow_new_entries === false);
    return source.map(function (candidate, index) {
      var scored = candidateScore(candidate);
      var state = candidateState(candidate, scored, historyAvailable, allowEntries);
      return {
        rank: index + 1,
        code: text(candidate.code || "—"),
        name: text(candidate.name || "未命名").replace(/^\*ST\s*/, "").trim(),
        theme: text(candidate.theme || candidate.best_concept || "—"),
        score: scored.score,
        closePct: scored.closePct,
        pop: scored.pop,
        gap: scored.gap,
        setup: text(candidate.setup || (scored.firstBreak ? "breakout" : (scored.pullback ? "pullback" : "watch"))),
        note: scored.note || "量价结构待确认",
        firstBreak: scored.firstBreak,
        profitEffect: candidate.profit_effect || candidate.profitEffect || null,
        state: state.label,
        tone: state.tone
      };
    }).sort(function (a, b) {
      return b.score - a.score;
    }).slice(0, 8).map(function (candidate, index) {
      candidate.rank = index + 1;
      return candidate;
    });
  }

  function aggregateCandidateProfit(candidates) {
    var horizons = {};
    ["5", "10", "20"].forEach(function (horizon) {
      var count = 0, weightedReturn = 0, weightedWin = 0;
      candidates.forEach(function (candidate) {
        var item = candidate.profitEffect && candidate.profitEffect.horizons && candidate.profitEffect.horizons[horizon];
        var n = item && Number(item.count) || 0;
        if (!n) return;
        count += n;
        weightedReturn += Number(item.avg_return || 0) * n;
        weightedWin += Number(item.win_rate || 0) * n;
      });
      horizons[horizon] = {
        count: count,
        avg_return: count ? weightedReturn / count : null,
        win_rate: count ? weightedWin / count : null
      };
    });
    return { signals: candidates.reduce(function (sum, candidate) { return sum + Number(candidate.profitEffect && candidate.profitEffect.signals || 0); }, 0), horizons: horizons, label: "候选个股汇总" };
  }

  function analyze(snapshot) {
    snapshot = snapshot || {};
    var trend = snapshot.trend || {};
    var direct = trend.decision || null;
    var legacyGate = marketGate(snapshot);
    var directMetrics = direct && direct.gate || {};
    var breadthRatio = num(directMetrics.eligible_ratio);
    var positiveRatio = num(directMetrics.positive_r20_ratio);
    var gate = direct ? {
      score: Math.round(clamp(normalize(breadthRatio, 0, 0.08) * 0.60 + normalize(positiveRatio, 0, 0.50) * 0.40, 0, 100)),
      breadth: breadthRatio * 100,
      positiveR20: positiveRatio * 100,
      fullAlignment: num(directMetrics.full_alignment_ratio) * 100,
      medianR20: num(directMetrics.median_r20) * 100,
      ratio: positiveRatio,
      excess: num(directMetrics.median_r20) * 100,
      blockers: []
    } : legacyGate;
    var historyAvailable = trend.historyAvailable === true;
    var candidates = buildCandidates(snapshot);
    var blockers = direct ? [] : gate.blockers.slice();
    if (direct && breadthRatio < num(directMetrics.eligible_ratio_min, 0.08)) blockers.push("趋势宽度" + gate.breadth.toFixed(1) + "%低于8%");
    if (direct && positiveRatio < num(directMetrics.positive_r20_ratio_min, 0.50)) blockers.push("近20日上涨占比低于50%");
    if (direct && direct.allow_new_entries === false && direct.reason) blockers.push(text(direct.reason));
    if (!historyAvailable) blockers.push("缺少全市场日线OHLCV，突破/回踩暂不作为真实触发");

    var status = direct ? (direct.allow_new_entries ? "ready" : "blocked") : (gate.blockers.length ? "blocked" : (historyAvailable && gate.score >= 65 ? "ready" : "observe"));
    var statusLabel = status === "ready" ? "可启动" : (status === "blocked" ? "暂关闭" : "观察");
    var trigger = direct ? text(direct.action) : (historyAvailable
      ? "收盘突破前60日高点，或突破后第一次缩量回踩确认"
      : "等待接入全市场日线数据后计算前60日高点、MA20/60、ATR和量价确认");
    var exit = "收盘跌破MA20/突破平台，或行业相对强度转负；高开过度、极端放量不追";
    var gated = trend.gated_strategies || {};
    var preferredEffect = gated["健康延续"] || gated["缩量回踩"] || trend.profit_effect || trend.profitEffect || aggregateCandidateProfit(candidates);
    var factorRows = direct ? [
      ["趋势宽度", Math.round(normalize(breadthRatio, 0, 0.08)), breadthRatio >= 0.08 ? "通过" : "不足"],
      ["近20日上涨占比", Math.round(clamp(positiveRatio * 100, 0, 100)), positiveRatio >= 0.50 ? "通过" : "不足"],
      ["完整多头排列", Math.round(normalize(num(directMetrics.full_alignment_ratio), 0, 0.16)), gate.fullAlignment.toFixed(1) + "%"],
      ["20日中位收益", Math.round(normalize(num(directMetrics.median_r20), -0.05, 0.08)), percent(gate.medianR20, 1)],
      ["个股日线因子", historyAvailable ? 100 : 0, historyAvailable ? "已接入" : "待接入"],
      ["突破追价", 35, "非默认触发"]
    ] : [
      ["市场闸门", gate.score, gate.score >= 65 ? "通过" : "观察"],
      ["行业扩散", Math.round(gate.breadth), gate.breadth >= 50 ? "通过" : "偏弱"],
      ["成交放量", Math.round(normalize(gate.ratio, 0, 1.5)), gate.ratio >= 1 ? "通过" : "不足"],
      ["行业超额", Math.round(normalize(gate.excess, -1, 2)), gate.excess > 0 ? "通过" : "偏弱"],
      ["个股日线因子", historyAvailable ? 100 : 0, historyAvailable ? "已接入" : "待接入"],
      ["过热否决", gate.blockers.length ? 35 : 85, gate.blockers.length ? "存在风险" : "未触发"]
    ];

    return {
      status: status,
      statusLabel: statusLabel,
      modeLabel: direct ? text(direct.mode) : statusLabel,
      directDecision: !!direct,
      score: gate.score,
      historyAvailable: historyAvailable,
      source: text(trend.source || "趋势交易引擎"),
      gate: gate,
      blockers: blockers,
      candidates: candidates,
      profitEffect: preferredEffect,
      profitEffectAvailable: trend.profit_effect_available === true || trend.profitEffectAvailable === true || candidates.some(function (candidate) { return candidate.profitEffect && Number(candidate.profitEffect.evaluated || 0) > 0; }),
      trigger: trigger,
      exit: exit,
      factorRows: factorRows
    };
  }

  global.TrendEngine = { analyze: analyze };
})(window);
