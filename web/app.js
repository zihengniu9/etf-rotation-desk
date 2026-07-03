(function initDashboard(globalScope) {
  const DATA_FILES = {
    pick: "../outputs/etf_rotation_pick.csv",
    rank: "../outputs/etf_rotation_rank.csv",
    pool: "../outputs/etf_theme_pool.csv",
    curve: "../outputs/etf_backtest_curve.csv",
    trades: "../outputs/etf_backtest_trades.csv",
    positions: "../outputs/etf_backtest_positions.csv",
    hot: "../outputs/etf_hot_rank.csv",
    status: "../outputs/etf_update_status.csv",
  };

  const BACKTEST_PERIODS = {
    week: { label: "周收益", rows: 5 },
    month: { label: "月收益", rows: 21 },
    year: { label: "年收益", rows: 252 },
    all: { label: "总收益", rows: Infinity },
  };

  const backtestState = {
    curveRows: [],
    tradeRows: [],
    activePeriod: "year",
  };

  const INDUSTRY_RULES = [
    { label: "半导体", pattern: /半导体|芯片|集成电路|电子50|电子ETF|半导体材料|半导体设备/ },
    { label: "科创", pattern: /科创|科综|双创/ },
    { label: "科技成长", pattern: /科技成长|新兴科技|科技策略|科技先锋|科技50|科技龙头|成长100/ },
    { label: "机器人", pattern: /机器人/ },
    { label: "人工智能", pattern: /人工智能|AI|算力|云计算|大数据|数据中心|智能/ },
    { label: "计算机", pattern: /计算机|软件|信创|信息技术|数字经济|物联网|工业互联|工业互联网/ },
    { label: "通信", pattern: /通信|5G|CPO|光通信/ },
    { label: "传媒游戏", pattern: /传媒|游戏|动漫|影视/ },
    { label: "证券", pattern: /证券|券商|金融科技/ },
    { label: "银行", pattern: /银行/ },
    { label: "保险", pattern: /保险/ },
    { label: "军工", pattern: /军工|国防|航天|航空/ },
    { label: "卫星", pattern: /卫星|商业航天/ },
    { label: "新能源车", pattern: /新能源车|智能车|汽车|电池|锂电/ },
    { label: "光伏", pattern: /光伏|太阳能/ },
    { label: "电力", pattern: /电力|公用事业/ },
    { label: "新能源", pattern: /储能|电力设备|新能源/ },
    { label: "旅游酒店", pattern: /旅游|酒店|餐饮/ },
    { label: "创新药", pattern: /创新药/ },
    { label: "医药", pattern: /医药|医疗|生物|疫苗|中药|制药/ },
    { label: "消费", pattern: /消费|食品|饮料|白酒|农业|养殖/ },
    { label: "家电家居", pattern: /家电|家具|家居/ },
    { label: "煤炭", pattern: /煤炭/ },
    { label: "能源", pattern: /能源|石油|天然气/ },
    { label: "有色金属", pattern: /有色|稀土|金属|矿业|钢铁/ },
    { label: "化工材料", pattern: /化工|材料|新材料|石化/ },
    { label: "房地产", pattern: /房地产|地产/ },
    { label: "基建建材", pattern: /基建|建筑|建材|工程/ },
    { label: "交通运输", pattern: /物流|运输|港口|航运/ },
    { label: "环保低碳", pattern: /环保|碳中和|绿色|长江保护/ },
    { label: "指数增强", pattern: /1000增强|2000增强|800增强|增强ETF/ },
    { label: "宽基指数", pattern: /上证50|上证380|上证580|中证500|中证800|中证1000|中证2000|国证2000|A500|深证成份|深证ETF/ },
    { label: "创业板", pattern: /创业板|中创400|BOCI创业|创精选/ },
    { label: "国企改革", pattern: /国有企业改革|国企改革/ },
    { label: "区域经济", pattern: /长三角|杭州湾区|之江凤凰|湖北新旧动能|浙江国资/ },
    { label: "海外宽基", pattern: /道琼斯|标普|纳斯达克|纳指|日经|德国|法国/ },
    { label: "虚拟现实", pattern: /VRETF|VR|虚拟现实/ },
    { label: "黄金", pattern: /黄金|金ETF/ },
    { label: "白银", pattern: /白银/ },
  ];

  function parseCsv(text) {
    const rows = [];
    let current = "";
    let row = [];
    let inQuotes = false;

    for (let i = 0; i < text.length; i += 1) {
      const char = text[i];
      const next = text[i + 1];
      if (char === '"' && inQuotes && next === '"') {
        current += '"';
        i += 1;
      } else if (char === '"') {
        inQuotes = !inQuotes;
      } else if (char === "," && !inQuotes) {
        row.push(current);
        current = "";
      } else if ((char === "\n" || char === "\r") && !inQuotes) {
        if (char === "\r" && next === "\n") i += 1;
        row.push(current);
        if (row.some((cell) => cell !== "")) rows.push(row);
        row = [];
        current = "";
      } else {
        current += char;
      }
    }

    if (current || row.length) {
      row.push(current);
      if (row.some((cell) => cell !== "")) rows.push(row);
    }

    if (rows.length === 0) return [];
    const headers = rows[0].map((header) => header.trim().replace(/^\uFEFF/, ""));
    return rows.slice(1).map((cells) => {
      const record = {};
      headers.forEach((header, index) => {
        record[header] = cells[index] === undefined ? "" : cells[index];
      });
      return record;
    });
  }

  function toNumber(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function isMissing(value) {
    return value === undefined || value === null || value === "" || !Number.isFinite(Number(value));
  }

  function formatPercent(value) {
    if (isMissing(value)) return "--";
    return `${(toNumber(value) * 100).toFixed(2)}%`;
  }

  function formatScore(value) {
    if (isMissing(value)) return "--";
    return toNumber(value).toFixed(3);
  }

  function formatFundSize(value) {
    if (isMissing(value)) return "--";
    const number = toNumber(value);
    if (number >= 100000000) return `${(number / 100000000).toFixed(1)}亿`;
    if (number >= 10000) return `${(number / 10000).toFixed(1)}万`;
    return number.toFixed(0);
  }

  function formatNetValue(value) {
    if (isMissing(value)) return "--";
    return toNumber(value).toFixed(4);
  }

  function formatSignedNetValue(value) {
    if (isMissing(value)) return "--";
    const number = toNumber(value);
    const prefix = number > 0 ? "+" : number < 0 ? "-" : "";
    return `${prefix}${Math.abs(number).toFixed(4)}`;
  }

  function formatSignedPercent(value) {
    if (isMissing(value)) return "--";
    const number = toNumber(value);
    const prefix = number > 0 ? "+" : number < 0 ? "-" : "";
    return `${prefix}${(Math.abs(number) * 100).toFixed(2)}%`;
  }

  function formatTradeWeight(row) {
    const value = toNumber(row.value);
    const equity = toNumber(row.equity_after);
    if (!Number.isFinite(value) || !Number.isFinite(equity) || equity <= 0) return "--";
    return formatPercent(value / equity);
  }

  function formatTradeReturn(row) {
    return String(row.action || "").toUpperCase() === "SELL" ? formatSignedPercent(row.realized_return) : "--";
  }

  function formatShares(value) {
    if (isMissing(value)) return "--";
    return toNumber(value).toFixed(4);
  }

  function formatHeat(value) {
    if (isMissing(value)) return "--";
    const number = toNumber(value);
    if (number >= 10000) return `${(number / 10000).toFixed(1)}万`;
    return number.toFixed(0);
  }

  function formatCountBadge(count, unit) {
    return `${Number(count) || 0}${unit}`;
  }

  function addThemeCandidate(candidates, value) {
    const text = String(value || "").trim();
    if (!text) return;
    const normalized = normalizeThemeLabel(text);
    if (normalized) candidates.add(normalized);

    const etfPrefix = text.split(/ETF/i)[0].trim();
    if (etfPrefix && etfPrefix !== text) {
      const normalizedPrefix = normalizeThemeLabel(etfPrefix);
      if (normalizedPrefix) candidates.add(normalizedPrefix);
    }

  }

  function getThemeCandidates(row) {
    const candidates = new Set();
    addThemeCandidate(candidates, row.theme);
    addThemeCandidate(candidates, row.name);
    return Array.from(candidates);
  }

  function buildHotThemeMap(hotRows) {
    const hotThemeMap = new Map();
    hotRows.forEach((row) => {
      const rankValue = Number(row.rank);
      if (!Number.isFinite(rankValue) || rankValue <= 0) return;
      getThemeCandidates(row).forEach((theme) => {
        const existing = hotThemeMap.get(theme);
        if (!existing || rankValue < existing.rankValue) {
          hotThemeMap.set(theme, {
            rank: row.rank || "",
            rankValue,
            code: row.code || "",
            name: row.name || "",
          });
        }
      });
    });
    return hotThemeMap;
  }

  function applyHotRanks(rankRows, hotRows) {
    const hotThemeMap = buildHotThemeMap(hotRows);
    return rankRows.map((row) => {
      const matchedHot = getThemeCandidates(row)
        .map((theme) => hotThemeMap.get(theme))
        .filter(Boolean)
        .sort((a, b) => a.rankValue - b.rankValue)[0];
      return {
        ...row,
        hotRank: matchedHot ? matchedHot.rank : "",
        hotCode: matchedHot ? matchedHot.code : "",
        hotName: matchedHot ? matchedHot.name : "",
      };
    });
  }

  function limitHotRows(rows, limit = 12) {
    return rows.slice(0, limit);
  }

  function limitRankRows(rows, limit = 50) {
    return rows.slice(0, limit);
  }

  function normalizeThemeLabel(theme) {
    const text = String(theme || "").trim();
    const matched = INDUSTRY_RULES.find((rule) => rule.pattern.test(text));
    return matched ? matched.label : "";
  }

  function buildIndustryRows(rows) {
    return rows
      .map((row) => {
        const theme = normalizeThemeLabel(`${row.theme || ""} ${row.name || ""}`);
        return theme ? { ...row, originalTheme: row.theme || "", theme } : null;
      })
      .filter(Boolean);
  }

  function buildThemeStrengthRows(rows, limit = 15) {
    const grouped = [];
    const seenThemes = new Set();
    rows
      .filter((row) => row && row.theme)
      .slice()
      .sort((a, b) => toNumber(b.score) - toNumber(a.score))
      .forEach((row) => {
        const theme = normalizeThemeLabel(`${row.theme || ""} ${row.name || ""}`);
        if (!theme || seenThemes.has(theme) || grouped.length >= limit) return;
        seenThemes.add(theme);
        grouped.push({ ...row, originalTheme: row.theme, theme });
      });
    return grouped;
  }

  function computeBacktestSummary(curveRows) {
    if (!curveRows.length) {
      return { netValue: "--", totalReturn: "--", maxDrawdown: "--", exposure: "--" };
    }
    const latest = curveRows[curveRows.length - 1];
    const startEquity = toNumber(curveRows[0].equity);
    const latestEquity = toNumber(latest.equity);
    const totalReturn = startEquity > 0 ? latestEquity / startEquity - 1 : 0;
    let peak = 0;
    let maxDrawdown = 0;
    curveRows.forEach((row) => {
      const equity = toNumber(row.equity);
      peak = Math.max(peak, equity);
      if (peak > 0) maxDrawdown = Math.min(maxDrawdown, equity / peak - 1);
    });
    return {
      netValue: formatNetValue(latest.equity),
      totalReturn: formatPercent(totalReturn),
      maxDrawdown: formatPercent(maxDrawdown),
      exposure: formatPercent(latest.exposure),
    };
  }

  function filterCurveRows(curveRows, period) {
    if (!curveRows.length) return [];
    const config = BACKTEST_PERIODS[period] || BACKTEST_PERIODS.all;
    if (!Number.isFinite(config.rows)) return curveRows.slice();
    return curveRows.slice(Math.max(0, curveRows.length - config.rows));
  }

  function getBacktestPeriodLabel(period) {
    return (BACKTEST_PERIODS[period] || BACKTEST_PERIODS.all).label;
  }

  function buildCurvePoints(curveRows, width, height, padding) {
    if (!curveRows.length) return "";
    const values = curveRows.map((row) => toNumber(row.equity));
    const minValue = Math.min(...values);
    const maxValue = Math.max(...values);
    const range = maxValue - minValue || 0.0001;
    const innerWidth = width - padding * 2;
    const innerHeight = height - padding * 2;
    return values
      .map((value, index) => {
        const x = padding + (curveRows.length === 1 ? 0 : (index / (curveRows.length - 1)) * innerWidth);
        const y = height - padding - ((value - minValue) / range) * innerHeight;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }

  function parseCurvePointList(points) {
    return points
      .split(" ")
      .map((point) => {
        const [x, y] = point.split(",").map(Number);
        return { x, y };
      })
      .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
  }

  function buildCurveAreaPath(points, width, height, padding) {
    const parsedPoints = parseCurvePointList(points);
    if (!parsedPoints.length) return "";
    const baseY = height - padding;
    const linePath = parsedPoints.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" L ");
    const first = parsedPoints[0];
    const latest = parsedPoints[parsedPoints.length - 1];
    return `M ${first.x.toFixed(1)},${baseY.toFixed(1)} L ${linePath} L ${latest.x.toFixed(1)},${baseY.toFixed(1)} Z`;
  }

  function buildChartLayout(width, height) {
    const leftAxisWidth = 58;
    const rightAxisWidth = 72;
    const bottomAxisHeight = 28;
    const plot = {
      left: leftAxisWidth,
      top: 10,
      right: width - rightAxisWidth,
      bottom: height - bottomAxisHeight,
    };
    plot.width = plot.right - plot.left;
    plot.height = plot.bottom - plot.top;
    return {
      plot,
      axis: {
        left: plot.left - 9,
        right: plot.right + 10,
        rightEdge: width - 6,
      },
      timeAxis: {
        y: height - 8,
      },
    };
  }

  function buildEquityAxisScale(curveRows) {
    const values = curveRows.map((row) => toNumber(row.equity)).filter((value) => Number.isFinite(value));
    const startEquity = values.length ? values[0] : 0;
    let rawMinValue = Math.min(...values, startEquity);
    let rawMaxValue = Math.max(...values, startEquity);
    if (!Number.isFinite(rawMinValue) || !Number.isFinite(rawMaxValue)) {
      rawMinValue = 0;
      rawMaxValue = 1;
    }
    if (rawMaxValue === rawMinValue) {
      const padding = Math.max(Math.abs(startEquity) * 0.01, 0.0001);
      rawMaxValue += padding;
    }
    const returnStep = chooseReturnTickStep(rawMinValue, rawMaxValue, startEquity);
    const minReturn = startEquity > 0 ? rawMinValue / startEquity - 1 : 0;
    const maxReturn = startEquity > 0 ? rawMaxValue / startEquity - 1 : 0;
    const minTickReturn = startEquity > 0 ? Math.floor((minReturn + 0.0000001) / returnStep) * returnStep : 0;
    const maxTickReturn = startEquity > 0 ? Math.ceil((maxReturn - 0.0000001) / returnStep) * returnStep : returnStep;
    const minValue = startEquity > 0 ? startEquity * (1 + minTickReturn) : rawMinValue;
    const maxValue = startEquity > 0 ? startEquity * (1 + maxTickReturn) : rawMaxValue;
    return {
      startEquity,
      minValue,
      maxValue,
      range: maxValue - minValue || 0.0001,
      minTickReturn,
      maxTickReturn,
      returnStep,
    };
  }

  function chooseReturnTickStep(minValue, maxValue, startEquity) {
    if (startEquity <= 0) return 0.1;
    const minReturn = minValue / startEquity - 1;
    const maxReturn = maxValue / startEquity - 1;
    const span = Math.max(0.1, maxReturn - minReturn);
    const steps = [0.1, 0.2, 0.5, 1, 2];
    return steps.find((step) => Math.ceil(span / step) + 1 <= 12) || steps[steps.length - 1];
  }

  function equityToY(value, scale, plot) {
    return plot.bottom - ((value - scale.minValue) / scale.range) * plot.height;
  }

  function buildYAxisTicks(scale, plot) {
    if (scale.startEquity > 0 && Number.isFinite(scale.minTickReturn) && Number.isFinite(scale.maxTickReturn)) {
      const ticks = [];
      const step = scale.returnStep || 0.1;
      for (let value = scale.maxTickReturn; value >= scale.minTickReturn - 0.0000001; value -= step) {
        const returnValue = Math.round(value * 1000000) / 1000000;
        const netValue = scale.startEquity * (1 + returnValue);
        ticks.push({
          value: netValue,
          y: equityToY(netValue, scale, plot),
          netLabel: formatAxisNetValue(netValue),
          returnLabel: formatPercent(returnValue),
        });
      }
      return ticks;
    }
    const middleValue = (scale.maxValue + scale.minValue) / 2;
    return [scale.maxValue, middleValue, scale.minValue].map((value) => ({
      value,
      y: equityToY(value, scale, plot),
      netLabel: formatAxisNetValue(value),
      returnLabel: scale.startEquity > 0 ? formatPercent(value / scale.startEquity - 1) : "--",
    }));
  }

  function formatAxisNetValue(value) {
    if (isMissing(value)) return "--";
    return toNumber(value).toFixed(1);
  }

  function buildCurvePointsInPlot(curveRows, plot, scale = buildEquityAxisScale(curveRows)) {
    if (!curveRows.length) return "";
    const values = curveRows.map((row) => toNumber(row.equity));
    return values
      .map((value, index) => {
        const x = plot.left + (curveRows.length === 1 ? 0 : (index / (curveRows.length - 1)) * plot.width);
        const y = equityToY(value, scale, plot);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }

  function buildCurveAreaPathForPlot(points, plot) {
    const parsedPoints = parseCurvePointList(points);
    if (!parsedPoints.length) return "";
    const linePath = parsedPoints.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" L ");
    const first = parsedPoints[0];
    const latest = parsedPoints[parsedPoints.length - 1];
    return `M ${first.x.toFixed(1)},${plot.bottom.toFixed(1)} L ${linePath} L ${latest.x.toFixed(1)},${plot.bottom.toFixed(1)} Z`;
  }

  function buildDateTicks(curveRows, maxTicks = 6) {
    if (!curveRows.length || maxTicks <= 0) return [];
    const count = Math.min(maxTicks, curveRows.length);
    const indexes = [];
    for (let index = 0; index < count; index += 1) {
      const pointIndex = count === 1 ? 0 : Math.round((index / (count - 1)) * (curveRows.length - 1));
      if (!indexes.includes(pointIndex)) indexes.push(pointIndex);
    }
    return indexes.map((index) => ({
      index,
      date: String(curveRows[index].date || ""),
      label: formatChartDate(curveRows[index].date),
    }));
  }

  function buildTradeMarkerPoints(curveRows, tradeRows, width, height, padding) {
    if (!curveRows.length || !tradeRows.length) return [];
    const curvePoints = parseCurvePointList(buildCurvePoints(curveRows, width, height, padding));
    return buildTradeMarkerPointsFromParsed(curveRows, tradeRows, curvePoints, {
      left: padding,
      right: width - padding,
      top: padding,
      bottom: height - padding,
    });
  }

  function buildTradeMarkerPointsInPlot(curveRows, tradeRows, plot, scale = buildEquityAxisScale(curveRows)) {
    if (!curveRows.length || !tradeRows.length) return [];
    const curvePoints = parseCurvePointList(buildCurvePointsInPlot(curveRows, plot, scale));
    return buildTradeMarkerPointsFromParsed(curveRows, tradeRows, curvePoints, plot);
  }

  function buildTradeMarkerPointsFromParsed(curveRows, tradeRows, curvePoints, bounds) {
    const pointByDate = new Map();
    curveRows.forEach((row, index) => {
      const point = curvePoints[index];
      if (point) pointByDate.set(String(row.date || ""), point);
    });
    const eligibleTrades = tradeRows
      .map((row) => ({ ...row, action: String(row.action || "").toUpperCase() }))
      .filter((row) => (row.action === "BUY" || row.action === "SELL") && pointByDate.has(String(row.date || "")));
    const tradesByDate = eligibleTrades.reduce((counts, row) => {
      const date = String(row.date || "");
      counts.set(date, (counts.get(date) || 0) + 1);
      return counts;
    }, new Map());
    const seenByDate = new Map();

    return eligibleTrades.map((row) => {
      const date = String(row.date || "");
      const point = pointByDate.get(date);
      const count = tradesByDate.get(date) || 1;
      const seen = seenByDate.get(date) || 0;
      seenByDate.set(date, seen + 1);
      const offset = (seen - (count - 1) / 2) * 8;
      return {
        ...row,
        x: Math.max(bounds.left, Math.min(bounds.right, point.x + offset)),
        y: Math.max(bounds.top, Math.min(bounds.bottom, point.y)),
      };
    });
  }

  function countTradeActions(rows) {
    return rows.reduce(
      (counts, row) => {
        const action = String(row.action || "").toUpperCase();
        if (action === "BUY") counts.buy += 1;
        if (action === "SELL") counts.sell += 1;
        return counts;
      },
      { buy: 0, sell: 0 },
    );
  }

  function formatPickTheme(pick) {
    if (pick.mode === "defense") return `${pick.theme || "防守"} · 防守建议`;
    return pick.theme || "--";
  }

  function formatPickReason(pick) {
    if (pick.mode === "defense") {
      const strength = formatScore(pick.market_strength || pick.score);
      const threshold = formatScore(pick.defense_threshold || 0.6);
      return `选择原因：市场强度 ${strength} 未超过 ${threshold}，主动进攻信号不足，优先防守类 ETF。`;
    }
    if (!pick.code) return "等待数据更新";
    const details = [
      formatScore(pick.score) !== "--" ? `强度评分 ${formatScore(pick.score)}` : "",
      formatPercent(pick.total_return) !== "--" ? `20日收益 ${formatPercent(pick.total_return)}` : "",
      formatFundSize(pick.fund_size) !== "--" ? `基金规模 ${formatFundSize(pick.fund_size)}` : "",
    ].filter(Boolean);
    const theme = pick.theme || "当前题材";
    if (!details.length) return `选择原因：${theme}处于榜单前列，符合当前进攻观察条件。`;
    return `选择原因：${theme}处于榜单前列，${details.join("，")}，兼顾强度、容量和近期动量。`;
  }

  function computeDashboardMetrics(rankRows, poolRows) {
    return {
      rankedCount: rankRows.length,
      themeCount: poolRows.length,
      topTheme: rankRows[0] ? rankRows[0].theme : "--",
    };
  }

  async function loadCsv(path) {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error(`${path} ${response.status}`);
    return parseCsv(await response.text());
  }

  function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  function renderPick(pick) {
    const block = document.querySelector(".pick-block");
    if (block) block.dataset.mode = pick.mode || "attack";
    setText("pick-code", pick.code || "--");
    setText("pick-name", pick.name || "--");
    setText("pick-theme", formatPickTheme(pick));
    setText("pick-reason", formatPickReason(pick));
    setText("pick-size", formatFundSize(pick.fund_size));
    setText("pick-return", formatPercent(pick.total_return));
    setText("pick-score", formatScore(pick.score));
    setText("pick-vol", formatPercent(pick.annual_vol));
  }

  function formatUpdateTime(statusRows) {
    const status = Array.isArray(statusRows) && statusRows.length ? statusRows[0] : {};
    const updatedAt = String(status.updated_at || "").trim();
    if (updatedAt) return updatedAt.replace("T", " ");
    return new Date().toLocaleString("zh-CN", { hour12: false });
  }

  function renderMetrics(rankRows, poolRows, statusRows = []) {
    const metrics = computeDashboardMetrics(rankRows, poolRows);
    setText("theme-count", String(metrics.themeCount));
    setText("ranked-count", String(metrics.rankedCount));
    setText("top-theme", metrics.topTheme);
    setText("updated-at", formatUpdateTime(statusRows));
  }

  function renderBacktest(curveRows, tradeRows, positionRows) {
    backtestState.curveRows = curveRows.slice();
    backtestState.tradeRows = tradeRows.slice();
    bindBacktestPeriodTabs();
    renderSelectedBacktestPeriod();
    renderBacktestPositions(positionRows);
    renderBacktestTrades(tradeRows);
  }

  function renderSelectedBacktestPeriod() {
    const periodRows = filterCurveRows(backtestState.curveRows, backtestState.activePeriod);
    const summary = computeBacktestSummary(periodRows);
    syncBacktestPeriodTabs();
    setText("bt-return-label", getBacktestPeriodLabel(backtestState.activePeriod));
    setText("bt-net-value", summary.netValue);
    setText("bt-total-return", summary.totalReturn);
    setText("bt-max-drawdown", summary.maxDrawdown);
    setText("bt-exposure", summary.exposure);
    renderBacktestChart(periodRows, backtestState.tradeRows);
  }

  function bindBacktestPeriodTabs() {
    if (bindBacktestPeriodTabs.hasBound) return;
    const buttons = document.querySelectorAll("[data-period]");
    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        backtestState.activePeriod = button.dataset.period || "all";
        renderSelectedBacktestPeriod();
      });
    });
    bindBacktestPeriodTabs.hasBound = true;
  }

  function syncBacktestPeriodTabs() {
    const buttons = document.querySelectorAll("[data-period]");
    buttons.forEach((button) => {
      const active = (button.dataset.period || "all") === backtestState.activePeriod;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function formatChartDate(value) {
    const text = String(value || "");
    const match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    return match ? `${match[2]}-${match[3]}` : text;
  }

  function renderBacktestChart(curveRows, tradeRows = []) {
    const svg = document.getElementById("backtest-chart");
    if (!svg) return;
    if (!curveRows.length) {
      svg.innerHTML = `<text x="360" y="112" text-anchor="middle" class="chart-empty">暂无回测数据</text>`;
      return;
    }
    const width = 720;
    const height = 360;
    const layout = buildChartLayout(width, height);
    const { plot } = layout;
    const axisScale = buildEquityAxisScale(curveRows);
    const points = buildCurvePointsInPlot(curveRows, plot, axisScale);
    const parsedPoints = parseCurvePointList(points);
    const areaPath = buildCurveAreaPathForPlot(points, plot);
    const latest = curveRows[curveRows.length - 1];
    const latestPoint = parsedPoints[parsedPoints.length - 1];
    const pillWidth = 58;
    const pillHeight = 22;
    const pillX = plot.right - pillWidth - 6;
    const pillY = Math.max(plot.top, Math.min(plot.bottom - pillHeight, latestPoint.y - pillHeight / 2));
    const yTicks = buildYAxisTicks(axisScale, plot);
    const horizontalGrids = yTicks
      .map((tick, index) => {
        const className = index === yTicks.length - 1 ? "chart-axis" : "chart-grid";
        return `<line x1="${plot.left}" y1="${tick.y.toFixed(1)}" x2="${plot.right}" y2="${tick.y.toFixed(1)}" class="${className}"></line>`;
      })
      .join("");
    const zeroY = equityToY(axisScale.startEquity, axisScale, plot);
    const yTickLabels = yTicks
      .map(
        (tick) =>
          `<text x="${layout.axis.left}" y="${tick.y.toFixed(1)}" text-anchor="end" class="chart-y-label chart-y-label-left">${tick.netLabel}</text>
           <text x="${layout.axis.right}" y="${tick.y.toFixed(1)}" class="chart-y-label chart-y-label-right">${tick.returnLabel}</text>`,
      )
      .join("");
    const dateTickRows = buildDateTicks(curveRows, 6);
    const verticalGrids = dateTickRows
      .slice(1, -1)
      .map((tick) => {
        const point = parsedPoints[tick.index];
        if (!point) return "";
        return `<line x1="${point.x.toFixed(1)}" y1="${plot.top}" x2="${point.x.toFixed(1)}" y2="${plot.bottom}" class="chart-grid chart-grid-vertical"></line>`;
      })
      .join("");
    const dateTicks = dateTickRows
      .map((tick, index, ticks) => {
        const point = parsedPoints[tick.index];
        if (!point) return "";
        const anchor = index === 0 ? "start" : index === ticks.length - 1 ? "end" : "middle";
        const x = Math.max(plot.left, Math.min(plot.right, point.x));
        return `<text x="${x.toFixed(1)}" y="${layout.timeAxis.y}" text-anchor="${anchor}" class="chart-label">${escapeHtml(tick.label)}</text>`;
      })
      .join("");
    const tradeMarkerRows = buildTradeMarkerPointsInPlot(curveRows, tradeRows, plot, axisScale);
    const markerCounts = countTradeActions(tradeMarkerRows);
    const tradeMarkers = tradeMarkerRows
      .map((marker) => {
        const className = marker.action === "BUY" ? "chart-marker-buy" : "chart-marker-sell";
        const title = `${marker.action} ${marker.code || ""} ${marker.name || ""} ${marker.date || ""} ${formatNetValue(marker.value)}`;
        return `<circle cx="${marker.x.toFixed(1)}" cy="${marker.y.toFixed(1)}" r="4.6" class="chart-marker ${className}"><title>${escapeHtml(title)}</title></circle>`;
      })
      .join("");
    const legendX = plot.left + 10;
    const legendY = plot.top + 10;
    const chartLegend = `
      <g class="chart-legend" transform="translate(${legendX}, ${legendY})">
        <rect x="0" y="0" width="192" height="30" rx="5" class="chart-legend-bg"></rect>
        <line x1="11" y1="15" x2="35" y2="15" class="chart-legend-line"></line>
        <text x="43" y="19" class="chart-legend-text">净值</text>
        <circle cx="86" cy="15" r="4" class="chart-marker-buy"></circle>
        <text x="96" y="19" class="chart-legend-text">买 ${markerCounts.buy}</text>
        <circle cx="137" cy="15" r="4" class="chart-marker-sell"></circle>
        <text x="147" y="19" class="chart-legend-text">卖 ${markerCounts.sell}</text>
      </g>`;
    svg.innerHTML = `
      <defs>
        <linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#ff3344" stop-opacity="0.26"></stop>
          <stop offset="62%" stop-color="#ff3344" stop-opacity="0.08"></stop>
          <stop offset="100%" stop-color="#ff3344" stop-opacity="0"></stop>
        </linearGradient>
      </defs>
      ${horizontalGrids}
      ${verticalGrids}
      <line x1="${plot.left}" y1="${plot.top}" x2="${plot.left}" y2="${plot.bottom}" class="chart-y-axis chart-y-axis-left"></line>
      <line x1="${plot.right}" y1="${plot.top}" x2="${plot.right}" y2="${plot.bottom}" class="chart-y-axis"></line>
      <path d="${areaPath}" class="chart-area"></path>
      <line x1="${plot.left}" y1="${zeroY.toFixed(1)}" x2="${plot.right}" y2="${zeroY.toFixed(1)}" class="chart-zero-guide"></line>
      <line x1="${plot.left}" y1="${latestPoint.y.toFixed(1)}" x2="${plot.right}" y2="${latestPoint.y.toFixed(1)}" class="chart-guide"></line>
      <polyline points="${points}" class="chart-line"></polyline>
      ${tradeMarkers}
      ${chartLegend}
      ${dateTicks}
      ${yTickLabels}
      <rect x="${pillX}" y="${pillY.toFixed(1)}" width="${pillWidth}" height="${pillHeight}" rx="3" class="chart-price-pill"></rect>
      <text x="${pillX + pillWidth / 2}" y="${(pillY + 15).toFixed(1)}" text-anchor="middle" class="chart-price-text">${formatNetValue(latest.equity)}</text>`;
  }

  function renderBacktestPositions(rows) {
    const container = document.getElementById("bt-positions");
    if (!container) return;
    if (!rows.length) {
      container.innerHTML = `<div class="mini-empty">暂无持仓</div>`;
      return;
    }
    container.innerHTML = rows
      .map(
        (row) => `
        <div class="holding-row">
          <div class="holding-title">
            <strong>${escapeHtml(row.code)}</strong>
            <span>${escapeHtml(row.name)}</span>
          </div>
          <div class="holding-metrics">
            <div>
              <span>仓位</span>
              <strong>${formatPercent(row.weight)}</strong>
            </div>
            <div>
              <span>成本 / 现价</span>
              <strong>${formatNetValue(row.entry_price)} / ${formatNetValue(row.last_price)}</strong>
            </div>
            <div>
              <span>浮盈</span>
              <strong class="${toNumber(row.unrealized_return) > 0 ? "positive" : ""}">${formatSignedPercent(row.unrealized_return)}</strong>
            </div>
          </div>
        </div>`,
      )
      .join("");
  }

  function renderBacktestTrades(rows) {
    const container = document.getElementById("bt-trades");
    if (!container) return;
    if (!rows.length) {
      container.innerHTML = `<div class="mini-empty">暂无交易</div>`;
      return;
    }
    container.innerHTML = rows
      .slice()
      .reverse()
      .map(
        (row) => `
        <div class="trade-row">
          <div class="trade-top">
            <span class="trade-action ${row.action === "BUY" ? "action-buy" : "action-sell"}">${escapeHtml(row.action)}</span>
            <strong>${escapeHtml(row.code)}</strong>
            <span>${escapeHtml(row.date)}</span>
          </div>
          <div class="trade-metrics">
            <div class="trade-field">
              <span>仓位</span>
              <strong>${formatTradeWeight(row)}</strong>
            </div>
            <div class="trade-field">
              <span>成交价</span>
              <strong>${formatNetValue(row.price)}</strong>
            </div>
            <div class="trade-field">
              <span>盈亏</span>
              <strong class="${toNumber(row.realized_return) > 0 ? "positive" : ""}">${formatTradeReturn(row)}</strong>
            </div>
          </div>
        </div>`,
      )
      .join("");
  }

  function renderHotList(rows) {
    const container = document.getElementById("hot-etfs");
    if (!container) return;
    const topRows = limitHotRows(rows);
    setText("hot-limit-badge", formatCountBadge(topRows.length, "只"));
    if (!rows.length) {
      container.innerHTML = `<div class="mini-empty">暂无热门 ETF</div>`;
      return;
    }
    container.innerHTML = topRows
      .map(
        (row) => `
        <div class="hot-row">
          <span class="hot-rank">${escapeHtml(row.rank)}</span>
          <div>
            <strong>${escapeHtml(row.code)}</strong>
            <span>${escapeHtml(row.name)}</span>
          </div>
          <em>${formatHeat(row.heat)}</em>
        </div>`,
      )
      .join("");
  }

  function renderRankTable(rows) {
    const body = document.getElementById("rank-body");
    if (!body) return;
    const topRows = limitRankRows(buildIndustryRows(rows));
    setText("rank-limit-badge", formatCountBadge(topRows.length, "只"));
    body.innerHTML = topRows
      .map(
        (row, index) => `
        <tr>
          <td class="numeric">${index + 1}</td>
          <td class="code">${escapeHtml(row.code)}</td>
          <td>${escapeHtml(row.name)}</td>
          <td>${escapeHtml(row.theme)}</td>
          <td>${row.hotRank ? `<span class="hot-badge" title="${escapeHtml(row.hotName || row.hotCode || "")}">热${escapeHtml(row.hotRank)}</span>` : ""}</td>
          <td class="numeric score">${formatScore(row.score)}</td>
          <td class="numeric positive">${formatPercent(row.total_return)}</td>
          <td class="numeric">${formatPercent(row.annual_vol)}</td>
          <td class="numeric">${formatFundSize(row.fund_size)}</td>
        </tr>`,
      )
      .join("");
  }

  function renderPoolTable(rows) {
    const body = document.getElementById("pool-body");
    if (!body) return;
    body.innerHTML = rows
      .map(
        (row) => `
        <tr>
          <td>${escapeHtml(row.theme)}</td>
          <td class="code">${escapeHtml(row.code)}</td>
          <td>${escapeHtml(row.name)}</td>
          <td class="numeric">${formatFundSize(row.fund_size)}</td>
          <td>${escapeHtml(row.scale_source || row.capacity_source || "")}</td>
          <td>${escapeHtml(row.fund_type || "")}</td>
        </tr>`,
      )
      .join("");
  }

  function renderBars(rows) {
    const container = document.getElementById("theme-bars");
    if (!container) return;
    const topRows = buildThemeStrengthRows(rows);
    setText("theme-limit-badge", formatCountBadge(topRows.length, "条"));
    const maxScore = Math.max(...topRows.map((row) => toNumber(row.score)), 0.01);
    container.innerHTML = topRows
      .map((row) => {
        const width = Math.max(4, (toNumber(row.score) / maxScore) * 100);
        return `
          <div class="bar-row">
            <div class="bar-label" title="${escapeHtml(row.theme)}">${escapeHtml(row.theme)}</div>
            <div class="bar-track"><div class="bar-fill" style="width:${width.toFixed(1)}%"></div></div>
            <div class="bar-value">${formatScore(row.score)}</div>
          </div>`;
      })
      .join("");
  }

  function matchesSearch(row, query) {
    if (!query) return true;
    const target = `${row.code || ""} ${row.name || ""} ${row.theme || ""}`.toLowerCase();
    return target.includes(query.toLowerCase());
  }

  function bindSearch(inputId, rows, render) {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.addEventListener("input", () => {
      render(rows.filter((row) => matchesSearch(row, input.value)));
    });
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  async function boot() {
    const status = document.getElementById("data-status");
    try {
      const [pickRows, rankRows, poolRows, curveRows, tradeRows, positionRows, hotRows, statusRows] = await Promise.all([
        loadCsv(DATA_FILES.pick),
        loadCsv(DATA_FILES.rank),
        loadCsv(DATA_FILES.pool),
        loadCsv(DATA_FILES.curve),
        loadCsv(DATA_FILES.trades),
        loadCsv(DATA_FILES.positions),
        loadCsv(DATA_FILES.hot),
        loadCsv(DATA_FILES.status),
      ]);
      const industryRankRows = buildIndustryRows(rankRows);
      const rankedRows = applyHotRanks(industryRankRows, hotRows);
      const topRankRows = limitRankRows(rankedRows);
      renderBacktest(curveRows, tradeRows, positionRows);
      renderPick(topRankRows[0] || pickRows[0] || {});
      renderMetrics(rankedRows, poolRows, statusRows);
      renderRankTable(topRankRows);
      renderPoolTable(poolRows);
      renderBars(rankedRows);
      renderHotList(hotRows);
      bindSearch("rank-search", topRankRows, renderRankTable);
      bindSearch("pool-search", poolRows, renderPoolTable);
      if (status) {
        status.textContent = "数据就绪";
        status.className = "status ok";
      }
    } catch (error) {
      if (status) {
        status.textContent = "加载失败";
        status.className = "status error";
      }
      const shell = document.querySelector(".shell");
      if (shell) {
        const message = document.createElement("div");
        message.className = "empty";
        message.textContent = `CSV 数据加载失败：${error.message}`;
        shell.appendChild(message);
      }
    }
  }

  const api = {
    parseCsv,
    formatPercent,
    formatScore,
    formatFundSize,
    formatNetValue,
    formatSignedNetValue,
    formatSignedPercent,
    formatTradeWeight,
    formatTradeReturn,
    formatShares,
    formatHeat,
    formatCountBadge,
    formatPickTheme,
    formatPickReason,
    formatUpdateTime,
    applyHotRanks,
    limitHotRows,
    limitRankRows,
    normalizeThemeLabel,
    buildIndustryRows,
    buildThemeStrengthRows,
    computeDashboardMetrics,
    computeBacktestSummary,
    filterCurveRows,
    buildChartLayout,
    buildEquityAxisScale,
    buildYAxisTicks,
    buildDateTicks,
    buildCurvePoints,
    buildCurveAreaPath,
    buildTradeMarkerPoints,
    countTradeActions,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    globalScope.ETF_DASHBOARD = api;
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", boot);
    } else {
      boot();
    }
  }
})(typeof window !== "undefined" ? window : globalThis);
