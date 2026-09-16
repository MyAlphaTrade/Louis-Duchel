// Reconstruit, a partir d'un BacktestResult SAUVEGARDE (champs agreges +
// liste de trades bruts), les formes attendues par les composants deja
// construits et valides pour l'ecran Backtesting (EquityCurve, TradeJournal)
// -- ecran "Stratégies découvertes" (Module 8, 2026-09-17) les reutilise tels
// quels plutot que de redessiner un graphique/tableau equivalent.
//
// Un resultat sauvegarde AVANT le correctif du 17/09/2026 ne contient ni
// `initial_capital` ni les champs complets de trade (direction/close_reason/
// volume/SL/TP/equity_after -- voir Backtesting.jsx `handleSave`). Ces
// enregistrements anciens restent lisibles (aucune migration, aucune valeur
// inventee) mais `hasFullDetail` retombe a false : l'appelant doit alors se
// limiter aux stats agregees natives du BacktestResult, jamais tenter de
// tracer une courbe ou un journal a partir de donnees absentes.

export function hasFullTradeDetail(result) {
  const trades = result?.trades || [];
  return result?.initial_capital != null && trades.length > 0 && trades[0].direction !== undefined;
}

// Courbe par TRADE FERME (pas par bougie -- seuls les trades sont
// persistes) : chaque point est le capital cumule reel juste apres un
// trade. Visuellement une courbe en escalier plutot que la courbe
// intra-bougie du live run, mais chaque valeur est un vrai cumul de profits
// reels, jamais interpolee.
export function equityCurveFromTrades(trades, initialCapital) {
  if (initialCapital == null) return [];
  const sorted = [...trades].sort(
    (a, b) => new Date(a.exit_time || 0) - new Date(b.exit_time || 0)
  );
  let equity = initialCapital;
  let peak = initialCapital;
  return sorted.map((t, i) => {
    equity += t.profit || 0;
    peak = Math.max(peak, equity);
    const drawdown = peak > 0 ? ((peak - equity) / peak) * 100 : 0;
    return {
      bar: i + 1,
      equity,
      balance: equity,
      drawdown,
      timestamp: t.exit_time,
    };
  });
}

// Recalcule les champs que SummaryStats attend mais qu'un BacktestResult
// n'agrege pas nativement (avgWin/avgLoss/expectancy/winLossRatio/
// tradesPerDay), a partir des trades bruts + start_date/end_date deja
// stockes. Retourne null si `hasFullTradeDetail(result)` est false --
// jamais un objet a moitie rempli avec des trous silencieux.
export function deriveMetricsFromSavedResult(result) {
  if (!hasFullTradeDetail(result)) return null;
  const trades = result.trades;
  const wins = trades.filter((t) => (t.profit || 0) > 0);
  const losses = trades.filter((t) => (t.profit || 0) < 0);
  const avgWin = wins.length ? wins.reduce((s, t) => s + t.profit, 0) / wins.length : 0;
  const avgLoss = losses.length
    ? Math.abs(losses.reduce((s, t) => s + t.profit, 0) / losses.length)
    : 0;
  const expectancy = trades.length
    ? trades.reduce((s, t) => s + (t.profit || 0), 0) / trades.length
    : 0;

  let tradesPerDay = null;
  if (result.start_date && result.end_date && result.total_trades) {
    const days = Math.max(
      1,
      (new Date(result.end_date) - new Date(result.start_date)) / 86400000
    );
    tradesPerDay = result.total_trades / days;
  }

  const initialCapital = result.initial_capital;
  const finalEquity = initialCapital + (result.total_profit || 0);
  const returnPct = initialCapital ? (result.total_profit / initialCapital) * 100 : 0;

  const metrics = {
    initialCapital,
    finalEquity,
    netProfit: result.total_profit,
    returnPct: +returnPct.toFixed(2),
    totalTrades: result.total_trades,
    bars: trades.length,
    winRate: result.win_rate,
    winningTrades: result.winning_trades,
    losingTrades: result.losing_trades,
    profitFactor: result.profit_factor,
    avgWin: +avgWin.toFixed(2),
    avgLoss: +avgLoss.toFixed(2),
    maxDrawdown: result.max_drawdown,
    expectancy: +expectancy.toFixed(2),
    winLossRatio: avgLoss ? +(avgWin / avgLoss).toFixed(2) : null,
    tradesPerDay: tradesPerDay != null ? +tradesPerDay.toFixed(2) : null,
  };

  return { metrics, equityCurve: equityCurveFromTrades(trades, initialCapital) };
}
