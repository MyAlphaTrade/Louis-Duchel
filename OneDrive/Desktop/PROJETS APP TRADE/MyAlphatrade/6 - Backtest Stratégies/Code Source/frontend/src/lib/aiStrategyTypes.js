/**
 * AI Strategy Types — Définit le format standard de stratégie AlphaTrade.
 *
 * Ce schéma sert de pont entre la sortie de l'IA et les modules existants
 * (Créateur de stratégies, Backtesting, Paper Trading, Signaux).
 * Il est volontairement aligné sur l'entity Strategy pour faciliter la
 * conversion future.
 */

export const STRATEGY_TEMPLATE = {
  name: "",
  description: "",
  asset_scope: "specific", // "specific" | "category" | "all"
  asset_symbols: [],
  asset_category: "",
  primary_timeframe: "M15",
  secondary_timeframes: [],
  market_profile: {
    sessions: [],
    volatility: "any",
    market_type: "any",
    ideal_conditions: "",
  },
  entry_conditions: {
    buy: [],
    sell: [],
  },
  exit_conditions: {
    take_profit: { type: "percent", value: 0 },
    stop_loss: { type: "percent", value: 0 },
    break_even: { enabled: false, trigger_pips: 0, offset_pips: 0 },
    trailing_stop: { enabled: false, type: "pips", distance: 0 },
    indicator_exit: { enabled: false, rule: "" },
    time_exit: { enabled: false, max_bars: 0 },
  },
  risk_management: {
    type: "percent",
    risk_value: 1,
    min_rr: 2,
    max_positions: 1,
    max_drawdown: 5,
  },
  trading_hours_filter: {
    enabled: false,
    start_hour: 0,
    end_hour: 24,
    days: [],
  },
  status: "draft",
  indicators: [],
  filters: [],
  configurable_parameters: [],
};

/**
 * Champs obligatoires pour qu'une stratégie soit considérée "complète".
 * Utilisé par le moteur de validation (13.7).
 */
export const REQUIRED_FIELDS = [
  { key: "name", label: "Nom de la stratégie", check: (s) => Boolean(s.name?.trim()) },
  { key: "asset", label: "Actif ou marché cible", check: (s) =>
    s.asset_scope === "all" ||
    (s.asset_symbols?.length > 0) ||
    Boolean(s.asset_category?.trim()) },
  { key: "timeframe", label: "Timeframe principal", check: (s) => Boolean(s.primary_timeframe) },
  { key: "entry_conditions", label: "Au moins une condition d'entrée", check: (s) =>
    (s.entry_conditions?.buy?.length > 0) || (s.entry_conditions?.sell?.length > 0) },
  { key: "stop_loss", label: "Stop Loss", check: (s) =>
    Boolean(s.exit_conditions?.stop_loss?.value > 0) },
  { key: "take_profit", label: "Take Profit", check: (s) =>
    Boolean(s.exit_conditions?.take_profit?.value > 0) },
  { key: "risk_value", label: "Risque par trade", check: (s) =>
    Boolean(s.risk_management?.risk_value > 0) },
];

/**
 * Vérifie quels champs obligatoires sont manquants.
 * @param {object} strategy — stratégie partielle
 * @returns {Array<{key,label}>} — champs manquants
 */
export function getMissingFields(strategy) {
  return REQUIRED_FIELDS.filter((f) => !f.check(strategy));
}

/**
 * Indique si la stratégie est complète et prête pour validation finale.
 */
export function isStrategyComplete(strategy) {
  return getMissingFields(strategy).length === 0;
}