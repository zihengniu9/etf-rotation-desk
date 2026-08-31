(function (scope) {
  "use strict";

  var modules = [
    {
      key: "trend",
      eyebrow: "TREND",
      title: "趋势交易",
      href: "./trend_engine.html",
      description: "主板个股趋势与历史赚钱效应",
      resolve: function (snapshot, analysis) {
        var trend = snapshot.trend || {};
        if (trend.historyAvailable && analysis.mode === "trend") {
          return { label: "优先研究", tone: "ready", detail: "行情模式匹配，先看健康延续与回踩" };
        }
        if (trend.historyAvailable) {
          return { label: "可研究", tone: "ready", detail: "先通过市场趋势闸门，再看个股触发" };
        }
        return { label: "仅观察", tone: "pending", detail: "等待全主板日线历史赚钱效应" };
      },
    },
    {
      key: "growth",
      eyebrow: "GROWTH",
      title: "成长股",
      href: "./growth_factor.html",
      description: "收入、利润、现金流与经营质量",
      resolve: function () {
        return { label: "研究观察", tone: "watch", detail: "基本面候选与交易触发保持分离" };
      },
    },
    {
      key: "dividend",
      eyebrow: "DIVIDEND QUALITY",
      title: "红利质量",
      href: "./dividend_factor.html",
      description: "估值、分红持续性与现金流覆盖",
      resolve: function (snapshot) {
        var dividend = snapshot.dividend || {};
        if (dividend.currentAvailable && dividend.backtestAvailable) {
          return { label: "已验证研究", tone: "ready", detail: "当前截面和历史验证均已接入" };
        }
        if (dividend.currentAvailable) {
          return { label: "截面已更新", tone: "watch", detail: "候选可复核，历史 Alpha 尚待回测" };
        }
        return { label: "等待数据", tone: "pending", detail: "尚未形成可审计的红利质量池" };
      },
    },
    {
      key: "short",
      eyebrow: "SHORT TERM",
      title: "短线观察",
      href: "./shortterm_dashboard.html",
      description: "情绪生态、梯队地位与竞价触发",
      resolve: function (snapshot, analysis) {
        var score = Number((snapshot.short || {}).score);
        if (analysis.mode === "short") {
          return { label: "优先研究", tone: "ready", detail: "M门控通过后再看S/E/Q个股信号" };
        }
        if (Number.isFinite(score) && score >= 75) {
          return { label: "谨慎研究", tone: "watch", detail: "情绪有支撑，但未成为当前主模式" };
        }
        return { label: "仅观察", tone: "pending", detail: "短线环境暂不支持主动追高" };
      },
    },
    {
      key: "industry",
      eyebrow: "INDUSTRY",
      title: "行业主线",
      href: "./industry_mainline_dashboard.html",
      description: "中期资金承载与行业扩散",
      resolve: function () {
        return { label: "中期参考", tone: "watch", detail: "行业主线不等于当日短线主线" };
      },
    },
    {
      key: "etf",
      eyebrow: "ETF ROTATION",
      title: "ETF轮动",
      href: "./etf_rotation.html",
      description: "工具趋势、波动、回撤与轮动",
      resolve: function (snapshot) {
        var etf = snapshot.etf || {};
        if (etf.mode === "attack") {
          return { label: "可研究", tone: "ready", detail: "策略强度偏进攻，仍需检查回撤与基准" };
        }
        return { label: "防守观察", tone: "watch", detail: "保持独立配置，不等同于股票热点" };
      },
    },
  ];

  scope.DASHBOARD_CONTRACT = {
    version: "dashboard-contract-v1",
    modules: modules,
    statusFor: function (module, snapshot, analysis) {
      return module.resolve(snapshot || {}, analysis || {});
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
