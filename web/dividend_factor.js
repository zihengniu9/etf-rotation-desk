(function () {
  "use strict";

  var data = window.DIVIDEND_FACTOR_SNAPSHOT || null;
  var state = { candidates: [], filtered: [], selected: null };
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (value) { return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) { return ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[char]; }); };
  var num = function (value, fallback) { var parsed = Number(value); return Number.isFinite(parsed) ? parsed : (fallback == null ? 0 : fallback); };
  var fixed = function (value, digits, suffix) { return value == null || !Number.isFinite(Number(value)) ? "—" : Number(value).toFixed(digits) + (suffix || ""); };
  var percentRatio = function (value, digits) { return value == null ? "—" : fixed(Number(value) * 100, digits == null ? 1 : digits, "%"); };

  function median(values) {
    var sorted = values.filter(function (value) { return Number.isFinite(Number(value)); }).map(Number).sort(function (a,b) { return a-b; });
    if (!sorted.length) return null;
    var mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  }

  function statusClass(status) {
    if (status === "红利质量优先") return "priority";
    if (status === "价值陷阱复核") return "trap";
    return "watch";
  }

  function unique(values) {
    return values.filter(function (value, index, array) { return value && array.indexOf(value) === index; }).sort(function (a,b) { return String(a).localeCompare(String(b), "zh-CN"); });
  }

  function populateSelect(id, values) {
    var select = $(id), first = select.options[0].outerHTML;
    select.innerHTML = first + unique(values).map(function (value) { return '<option value="'+esc(value)+'">'+esc(value)+'</option>'; }).join("");
  }

  function renderHero() {
    var universe = data.universe || {}, distribution = data.industry_distribution || [];
    var priority = state.candidates.filter(function (item) { return item.status === "红利质量优先"; });
    var top = state.candidates[0];
    $("data-date").textContent = "数据日期 " + (data.data_as_of || "—");
    $("data-source").textContent = data.source || "数据源未注明";
    $("validation-state").textContent = data.validation && data.validation.panda_backtest === "pending_parameter_confirmation" ? "历史回测待确认" : "回测状态已更新";
    $("valid-count").textContent = String(universe.valid == null ? "—" : universe.valid);
    $("matched-count").textContent = "问财匹配 " + (universe.matched == null ? "—" : universe.matched) + " 只";
    $("priority-count").textContent = String(priority.length);
    $("median-yield").textContent = fixed(median(state.candidates.map(function (item) { return item.dividend_yield; })), 2, "%");
    $("industry-share").textContent = distribution.length ? fixed(num(distribution[0].share) * 100, 1, "%") : "—";
    $("industry-name").textContent = distribution.length ? distribution[0].industry : "有效池分布";
    $("hero-title").textContent = top ? "当前红利质量池可研究，优先复核 " + top.name : "当前没有通过门槛的候选";
    $("hero-copy").textContent = top ?
      "有效池共 " + universe.valid + " 只，当前行业分散候选 " + state.candidates.length + " 只。第一名 " + top.name + " 的 DQC 为 " + fixed(top.score,2) + "，股息率 " + fixed(top.dividend_yield,2,"%") + "；这仍是截面研究结论，不是买入触发。" :
      "当前数据未形成可展示候选，请检查数据覆盖与筛选条件。";
  }

  function renderTable() {
    var query = $("search").value.trim().toLowerCase();
    var status = $("status-filter").value, industry = $("industry-filter").value, board = $("board-filter").value;
    state.filtered = state.candidates.filter(function (item) {
      var haystack = [item.name,item.code,item.industry,item.market_type].join(" ").toLowerCase();
      return (!query || haystack.indexOf(query) >= 0) && (!status || item.status === status) && (!industry || item.industry === industry) && (!board || item.market_type === board);
    });
    $("result-count").textContent = "显示 " + state.filtered.length + " / " + state.candidates.length + " 只";
    $("candidate-body").innerHTML = state.filtered.length ? state.filtered.map(function (item) {
      var risks = item.risk_flags && item.risk_flags.length ? item.risk_flags.join("；") : "无";
      var changeClass = num(item.latest_change) < 0 ? "down" : "";
      return '<tr tabindex="0" data-code="'+esc(item.code)+'">'+
        '<td><div class="stock"><span class="rank">'+item.rank+'</span><div><strong>'+esc(item.name)+'</strong><small>'+esc(item.code)+' · '+esc(item.industry)+' · <span class="'+changeClass+'">'+fixed(item.latest_change,2,"%")+'</span></small></div></div></td>'+
        '<td><span class="status '+statusClass(item.status)+'">'+esc(item.status)+'</span></td>'+
        '<td><span class="score">'+fixed(item.score,2)+'</span></td>'+
        '<td><div class="subscores" title="估值 / 分红 / 现金流"><span>'+fixed(item.valuation_score,0)+'</span><span>'+fixed(item.dividend_score,0)+'</span><span>'+fixed(item.cashflow_score,0)+'</span></div></td>'+
        '<td><span class="yield">'+fixed(item.dividend_yield,2,"%")+'</span></td>'+
        '<td>'+fixed(item.pe_ttm,2)+' / '+fixed(item.pb,2)+'</td>'+
        '<td>'+fixed(item.cash_conversion,2)+'×</td>'+
        '<td>'+fixed(item.cash_coverage,2)+'×</td>'+
        '<td>'+(risks === "无" ? '<span class="risk-none">无</span>' : '<span class="risk-flags">'+esc(risks)+'</span>')+'</td></tr>';
    }).join("") : '<tr><td colspan="9" class="empty">当前筛选条件下没有候选。</td></tr>';
    Array.prototype.forEach.call($("candidate-body").querySelectorAll("tr[data-code]"), function (row) {
      function select() { var found = state.candidates.find(function (item) { return item.code === row.dataset.code; }); if (found) renderDetail(found); }
      row.addEventListener("click", select);
      row.addEventListener("keydown", function (event) { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } });
    });
  }

  function stat(label,value) { return '<div class="detail-stat"><span>'+esc(label)+'</span><strong>'+esc(value)+'</strong></div>'; }
  function bar(label,value) { return '<div class="bar-line"><span>'+esc(label)+'</span><div class="bar-track"><i style="--value:'+Math.max(0,Math.min(100,num(value)))+'"></i></div><strong>'+fixed(value,0)+'</strong></div>'; }

  function renderDetail(item) {
    state.selected = item;
    var risks = item.risk_flags && item.risk_flags.length ? item.risk_flags.join("；") : "未触发分红下降、利润下降、高派息或弱现金覆盖旗标。";
    $("detail-panel").innerHTML = '<div class="detail-head"><div><span class="status '+statusClass(item.status)+'">'+esc(item.status)+'</span><h3>'+esc(item.name)+' <small>'+esc(item.code)+'</small></h3><p>'+esc(item.industry)+' · '+esc(item.market_type)+' · 数据覆盖 '+percentRatio(item.factor_coverage,0)+'</p></div><div class="score-orb" style="--score:'+num(item.score)+'" data-score="'+fixed(item.score,1)+'" aria-label="DQC '+fixed(item.score,1)+'分"></div></div>'+
      '<div class="detail-stats">'+stat("股息率",fixed(item.dividend_yield,2,"%"))+stat("PE / PB",fixed(item.pe_ttm,2)+" / "+fixed(item.pb,2))+stat("三年派息率中位数",percentRatio(item.average_payout,1))+stat("分红年化变化",percentRatio(item.dividend_cagr,1))+stat("现金 / 利润",fixed(item.cash_conversion,2)+"×")+stat("现金 / 分红",fixed(item.cash_coverage,2)+"×")+stat("分红稳定度",fixed(num(item.dividend_stability)*100,1,"%"))+stat("最新价",fixed(item.latest_price,2))+"</div>"+
      '<div class="factor-bars">'+bar("估值",item.valuation_score)+bar("分红",item.dividend_score)+bar("现金流",item.cashflow_score)+'</div>'+
      '<div class="detail-risk"><strong>风险复核：</strong>'+esc(risks)+'<br><strong>执行边界：</strong>本页只进入基本面观察池；是否交易仍需独立的趋势/右侧价格触发与仓位规则。</div>';
  }

  function renderMethod() {
    var formula = data.formula || {}, distribution = data.industry_distribution || [];
    $("formula-total").textContent = formula.total || "DQC = 30%估值 + 35%分红 + 35%现金流质量";
    $("method-list").innerHTML = [
      ["V · 估值",formula.valuation], ["D · 分红",formula.dividend], ["C · 现金流",formula.cashflow], ["行业中性化",formula.neutralization]
    ].map(function (item) { return '<li><strong>'+esc(item[0])+'</strong><span>'+esc(item[1] || "—")+'</span></li>'; }).join("");
    var maxShare = distribution.reduce(function (max,item) { return Math.max(max,num(item.share)); },0) || 1;
    $("industry-bars").innerHTML = '<h3>有效池行业分布</h3>' + distribution.slice(0,6).map(function (item) {
      return '<div class="industry-row"><span>'+esc(item.industry)+'</span><div class="bar-track"><i style="--share:'+(num(item.share)/maxShare*100)+'"></i></div><strong>'+fixed(num(item.share)*100,1,"%")+'</strong></div>';
    }).join("");
    $("research-note").textContent = (data.gates && data.gates.note ? data.gates.note : "当前截面不代表交易触发。") + " 金融行业因现金流口径不可比而排除。";
  }

  function initialize(snapshot) {
    data = snapshot;
    state.candidates = Array.isArray(data.candidates) ? data.candidates : [];
    populateSelect("status-filter", state.candidates.map(function (item) { return item.status; }));
    populateSelect("industry-filter", state.candidates.map(function (item) { return item.industry; }));
    populateSelect("board-filter", state.candidates.map(function (item) { return item.market_type; }));
    renderHero(); renderMethod(); renderTable();
    if (state.candidates.length) renderDetail(state.candidates[0]);
    else $("detail-panel").innerHTML = '<div class="empty">没有可展示的个股证据。</div>';
  }

  ["search","status-filter","industry-filter","board-filter"].forEach(function (id) { $(id).addEventListener(id === "search" ? "input" : "change", renderTable); });
  if (data) initialize(data);
  else {
    fetch("../outputs/dividend_factor_snapshot.json?ts=" + Date.now(), {cache:"no-store"}).then(function (response) { if (!response.ok) throw new Error(String(response.status)); return response.json(); }).then(initialize).catch(function () {
      $("candidate-body").innerHTML = '<tr><td colspan="9" class="empty">未读取到红利因子数据，请先运行 update_dividend_factor.py。</td></tr>';
      $("hero-title").textContent = "红利质量数据未加载";
    });
  }
})();
