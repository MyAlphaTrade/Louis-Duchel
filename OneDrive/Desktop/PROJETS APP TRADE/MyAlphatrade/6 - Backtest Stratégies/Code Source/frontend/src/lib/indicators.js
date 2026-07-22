// Indicators registry — describes all supported indicators, their parameters,
// and the operators available for building entry/exit conditions.
// This is a code-side registry (not a DB entity) so the strategy form can
// dynamically render parameter fields based on the chosen indicator.

export const INDICATOR_CATEGORIES = [
  "Tendance",
  "Oscillateur",
  "Volatilité",
  "Volume",
  "Price Action",
  "Smart Money",
];

export const INDICATORS = [
  // ── Tendance ──
  {
    id: "ema",
    name: "EMA",
    category: "Tendance",
    description: "Moyenne mobile exponentielle",
    params: [
      { key: "period", label: "Période", default: 9, type: "number", min: 1, max: 500 },
    ],
    supports_cross: true,
    supports_value: true,
  },
  {
    id: "sma",
    name: "SMA",
    category: "Tendance",
    description: "Moyenne mobile simple",
    params: [
      { key: "period", label: "Période", default: 20, type: "number", min: 1, max: 500 },
    ],
    supports_cross: true,
    supports_value: true,
  },
  {
    id: "macd",
    name: "MACD",
    category: "Tendance",
    description: "Convergence/Divergence des moyennes mobiles",
    params: [
      { key: "fast", label: "Période rapide", default: 12, type: "number", min: 1, max: 100 },
      { key: "slow", label: "Période lente", default: 26, type: "number", min: 1, max: 200 },
      { key: "signal", label: "Période signal", default: 9, type: "number", min: 1, max: 100 },
    ],
    supports_cross: true,
  },
  {
    id: "adx",
    name: "ADX",
    category: "Tendance",
    description: "Indice directionnel moyen — force de la tendance",
    params: [
      { key: "period", label: "Période", default: 14, type: "number", min: 1, max: 100 },
    ],
    supports_value: true,
  },
  {
    id: "ichimoku",
    name: "Ichimoku",
    category: "Tendance",
    description: "Nuage d'Ichimoku — équilibre des prix",
    params: [
      { key: "conversion", label: "Tenkan (conversion)", default: 9, type: "number", min: 1, max: 100 },
      { key: "base", label: "Kijun (base)", default: 26, type: "number", min: 1, max: 200 },
      { key: "span", label: "Senkou Span", default: 52, type: "number", min: 1, max: 400 },
    ],
    supports_cross: true,
  },

  // ── Oscillateurs ──
  {
    id: "rsi",
    name: "RSI",
    category: "Oscillateur",
    description: "Indice de force relative",
    params: [
      { key: "period", label: "Période", default: 14, type: "number", min: 1, max: 100 },
    ],
    supports_value: true,
    supports_zones: true,
    zones: { overbought: 70, oversold: 30 },
  },
  {
    id: "stochastic",
    name: "Stochastic",
    category: "Oscillateur",
    description: "Oscillateur stochastique",
    params: [
      { key: "k_period", label: "%K", default: 14, type: "number", min: 1, max: 100 },
      { key: "d_period", label: "%D", default: 3, type: "number", min: 1, max: 50 },
      { key: "smooth", label: "Lissage", default: 3, type: "number", min: 1, max: 50 },
    ],
    supports_cross: true,
    supports_zones: true,
    zones: { overbought: 80, oversold: 20 },
  },

  // ── Volatilité ──
  {
    id: "atr",
    name: "ATR",
    category: "Volatilité",
    description: "Average True Range — volatilité",
    params: [
      { key: "period", label: "Période", default: 14, type: "number", min: 1, max: 100 },
    ],
    supports_value: true,
  },
  {
    id: "bollinger",
    name: "Bollinger Bands",
    category: "Volatilité",
    description: "Bandes de Bollinger",
    params: [
      { key: "period", label: "Période", default: 20, type: "number", min: 1, max: 200 },
      { key: "std_dev", label: "Écart-type", default: 2, type: "number", min: 0.5, max: 5, step: 0.1 },
    ],
    supports_cross: true,
  },

  // ── Volume ──
  {
    id: "volume",
    name: "Volume",
    category: "Volume",
    description: "Volume de transactions",
    params: [
      { key: "ma_period", label: "Période MA", default: 20, type: "number", min: 1, max: 200 },
    ],
    supports_value: true,
  },

  // ── Price Action ──
  {
    id: "support_resistance",
    name: "Support / Résistance",
    category: "Price Action",
    description: "Niveaux de support et résistance",
    params: [
      { key: "lookback", label: "Bars de référence", default: 50, type: "number", min: 10, max: 500 },
      { key: "touches", label: "Nombre de touches", default: 2, type: "number", min: 2, max: 10 },
    ],
    supports_value: true,
  },
  {
    id: "breakout",
    name: "Breakout",
    category: "Price Action",
    description: "Cassure de niveau",
    params: [
      { key: "lookback", label: "Période de référence", default: 20, type: "number", min: 5, max: 500 },
      { key: "direction", label: "Direction", default: "both", type: "select", options: ["both", "up", "down"] },
    ],
    supports_value: true,
  },

  // ── Smart Money ──
  {
    id: "liquidity",
    name: "Liquidité",
    category: "Smart Money",
    description: "Zones de liquidité — chasse de stops",
    params: [
      { key: "lookback", label: "Bars de référence", default: 100, type: "number", min: 10, max: 1000 },
      { key: "type", label: "Type", default: "both", type: "select", options: ["both", "buyside", "sellside"] },
    ],
    supports_value: true,
  },
  {
    id: "smc",
    name: "Smart Money Concepts",
    category: "Smart Money",
    description: "Order blocks, fair value gaps, change of character",
    params: [
      { key: "pattern", label: "Pattern", default: "ob", type: "select", options: [
        { value: "ob", label: "Order Block" },
        { value: "fvg", label: "Fair Value Gap" },
        { value: "chosch", label: "Change of Character" },
        { value: "bosi", label: "Break of Structure" },
      ] },
      { key: "lookback", label: "Bars de référence", default: 50, type: "number", min: 5, max: 500 },
    ],
    supports_value: true,
  },
];

export const OPERATORS = [
  { id: "crosses_above", label: "Croise au-dessus de", requires_target: "indicator" },
  { id: "crosses_below", label: "Croise en-dessous de", requires_target: "indicator" },
  { id: "greater_than", label: "Supérieur à", requires_target: "value" },
  { id: "less_than", label: "Inférieur à", requires_target: "value" },
  { id: "equals", label: "Égal à", requires_target: "value" },
  { id: "in_zone", label: "Dans la zone", requires_target: "none" },
  { id: "out_zone", label: "Hors de la zone", requires_target: "none" },
];

export const TRADING_SESSIONS = [
  { id: "sydney", label: "Sydney", start: 22, end: 7, color: "cyan" },
  { id: "tokyo", label: "Tokyo", start: 0, end: 9, color: "rose" },
  { id: "london", label: "Londres", start: 8, end: 17, color: "amber" },
  { id: "new_york", label: "New York", start: 13, end: 22, color: "emerald" },
];

export const MARKET_TYPES = [
  { id: "trend", label: "Tendance", description: "Marché directionnel" },
  { id: "range", label: "Range", description: "Marché latéral" },
  { id: "breakout", label: "Breakout", description: "Cassure de range" },
  { id: "any", label: "Indifférent", description: "Tous types de marché" },
];

export const VOLATILITY_LEVELS = [
  { id: "low", label: "Faible" },
  { id: "medium", label: "Moyenne" },
  { id: "high", label: "Forte" },
  { id: "any", label: "Indifférent" },
];

// Helpers
export const getIndicator = (id) => INDICATORS.find((i) => i.id === id);
export const getIndicatorsByCategory = (category) =>
  INDICATORS.filter((i) => i.category === category);
export const getOperator = (id) => OPERATORS.find((o) => o.id === id);