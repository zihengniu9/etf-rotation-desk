window.DIVIDEND_FACTOR_SNAPSHOT = {
  "version": "dividend-quality-v1",
  "data_as_of": "2026-10-22",
  "source": "同花顺问财 · hithink-astock-selector",
  "universe": {
    "definition": "沪深A股非ST、非金融、上市满3年；近3年分红、经营现金流和归母净利润均为正",
    "matched": 3,
    "normalized": 3,
    "valid": 3,
    "financials_excluded": true,
    "annual_periods": [
      2023,
      2024,
      2025
    ],
    "industry_cap": 2
  },
  "formula": {
    "total": "DQC = 30%估值 + 35%分红 + 35%现金流质量",
    "valuation": "60%盈利收益率(E/P) + 40%账面收益率(B/P)",
    "dividend": "45%股息率 + 20%派息安全 + 20%分红稳定 + 15%分红增长",
    "cashflow": "35%现金利润匹配 + 25%现金流稳定 + 20%现金覆盖分红 + 20%利润稳定",
    "neutralization": "单项排名 = 40%全市场分位 + 60%同行业分位（行业样本不足5只时仅用全市场）"
  },
  "gates": {
    "priority": "DQC≥75、股息率≥2.5%、无风险旗标",
    "watch": "DQC≥65、风险旗标不超过1项",
    "value_trap": "风险旗标达到2项：分红下降、利润下降、高派息或现金利润不匹配",
    "note": "这是当前截面研究排序，不代表买入触发；需等待历史回测和价格侧触发验证。"
  },
  "validation": {
    "current_cross_section": true,
    "panda_backtest": "pending_parameter_confirmation",
    "backtest_claim_allowed": false
  },
  "industry_distribution": [
    {
      "industry": "电机",
      "count": 2,
      "share": 0.6667
    },
    {
      "industry": "光学光电子",
      "count": 1,
      "share": 0.3333
    }
  ],
  "raw_top": [
    {
      "rank": 1,
      "code": "002249",
      "name": "大洋电机",
      "industry": "电机",
      "market_type": "主板",
      "latest_price": 7.06,
      "latest_change": 9.97,
      "market_cap": 17472085324.26,
      "score": 83.75,
      "valuation_score": 86.67,
      "dividend_score": 71.67,
      "cashflow_score": 93.33,
      "dividend_yield": 2.72,
      "pe_ttm": 19.43,
      "pb": 1.79,
      "average_payout": 0.6696,
      "cash_conversion": 2.79,
      "cash_coverage": 3.87,
      "dividend_stability": 0.793,
      "dividend_cagr": 0.203,
      "factor_coverage": 1.0,
      "status": "红利质量优先",
      "risk_flags": []
    },
    {
      "rank": 2,
      "code": "600261",
      "name": "阳光照明",
      "industry": "光学光电子",
      "market_type": "主板",
      "latest_price": 3.6,
      "latest_change": 10.09,
      "market_cap": 4806190677.6,
      "score": 76.96,
      "valuation_score": 80.0,
      "dividend_score": 77.99,
      "cashflow_score": 73.33,
      "dividend_yield": 3.86,
      "pe_ttm": 33.99,
      "pb": 1.42,
      "average_payout": 0.9204,
      "cash_conversion": 1.27,
      "cash_coverage": 1.37,
      "dividend_stability": 0.965,
      "dividend_cagr": 0.0,
      "factor_coverage": 1.0,
      "status": "稳健观察",
      "risk_flags": [
        "派息率超过85%"
      ]
    },
    {
      "rank": 3,
      "code": "301023",
      "name": "奕帆传动",
      "industry": "电机",
      "market_type": "创业板",
      "latest_price": 32.48,
      "latest_change": 19.99,
      "market_cap": 3030399590.4,
      "score": 37.27,
      "valuation_score": 33.33,
      "dividend_score": 44.59,
      "cashflow_score": 33.33,
      "dividend_yield": 2.08,
      "pe_ttm": 50.74,
      "pb": 3.67,
      "average_payout": 0.9811,
      "cash_conversion": 0.54,
      "cash_coverage": 0.61,
      "dividend_stability": 0.807,
      "dividend_cagr": 0.1695,
      "factor_coverage": 1.0,
      "status": "价值陷阱复核",
      "risk_flags": [
        "派息率超过85%",
        "经营现金/利润中位数低于0.8"
      ]
    }
  ],
  "candidates": [
    {
      "rank": 1,
      "code": "002249",
      "name": "大洋电机",
      "industry": "电机",
      "market_type": "主板",
      "latest_price": 7.06,
      "latest_change": 9.97,
      "market_cap": 17472085324.26,
      "score": 83.75,
      "valuation_score": 86.67,
      "dividend_score": 71.67,
      "cashflow_score": 93.33,
      "dividend_yield": 2.72,
      "pe_ttm": 19.43,
      "pb": 1.79,
      "average_payout": 0.6696,
      "cash_conversion": 2.79,
      "cash_coverage": 3.87,
      "dividend_stability": 0.793,
      "dividend_cagr": 0.203,
      "factor_coverage": 1.0,
      "status": "红利质量优先",
      "risk_flags": []
    },
    {
      "rank": 2,
      "code": "600261",
      "name": "阳光照明",
      "industry": "光学光电子",
      "market_type": "主板",
      "latest_price": 3.6,
      "latest_change": 10.09,
      "market_cap": 4806190677.6,
      "score": 76.96,
      "valuation_score": 80.0,
      "dividend_score": 77.99,
      "cashflow_score": 73.33,
      "dividend_yield": 3.86,
      "pe_ttm": 33.99,
      "pb": 1.42,
      "average_payout": 0.9204,
      "cash_conversion": 1.27,
      "cash_coverage": 1.37,
      "dividend_stability": 0.965,
      "dividend_cagr": 0.0,
      "factor_coverage": 1.0,
      "status": "稳健观察",
      "risk_flags": [
        "派息率超过85%"
      ]
    },
    {
      "rank": 3,
      "code": "301023",
      "name": "奕帆传动",
      "industry": "电机",
      "market_type": "创业板",
      "latest_price": 32.48,
      "latest_change": 19.99,
      "market_cap": 3030399590.4,
      "score": 37.27,
      "valuation_score": 33.33,
      "dividend_score": 44.59,
      "cashflow_score": 33.33,
      "dividend_yield": 2.08,
      "pe_ttm": 50.74,
      "pb": 3.67,
      "average_payout": 0.9811,
      "cash_conversion": 0.54,
      "cash_coverage": 0.61,
      "dividend_stability": 0.807,
      "dividend_cagr": 0.1695,
      "factor_coverage": 1.0,
      "status": "价值陷阱复核",
      "risk_flags": [
        "派息率超过85%",
        "经营现金/利润中位数低于0.8"
      ]
    }
  ],
  "query": "2026年10月22日沪深A股非ST且非金融，上市满3年，2023年、2024年、2025年均有现金分红，股息率大于2%，市盈率TTM大于0，市净率大于0，2023年、2024年、2025年经营活动现金流量净额均为正，2023年、2024年、2025年归属于母公司股东的净利润均为正，显示股票代码、股票简称、股票市场类型、所属同花顺行业、最新价、最新涨跌幅、总市值、股息率、市盈率TTM、市净率、2023年现金分红总额、2024年现金分红总额、2025年现金分红总额、2023年经营活动现金流量净额、2024年经营活动现金流量净额、2025年经营活动现金流量净额、2023年归属于母公司股东的净利润、2024年归属于母公司股东的净利润、2025年归属于母公司股东的净利润",
  "updated_at": "2026-10-22T16:27:27+08:00"
};
