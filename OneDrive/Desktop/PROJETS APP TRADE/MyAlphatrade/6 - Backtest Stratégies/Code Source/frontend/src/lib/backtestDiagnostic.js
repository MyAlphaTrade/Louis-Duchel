// Diagnostic de backtest — traduit les métriques brutes (déjà calculées par
// backtestEngine.js) en un verdict et des pistes d'ajustement concrètes.
// Purement déterministe (pas d'IA) : mêmes chiffres, même diagnostic à
// chaque fois — sert de base toujours disponible, que l'IA soit configurée
// ou non. Aucune valeur n'est inventée : tout dérive directement des trades
// réellement produits par ce backtest.

const MIN_TRADES_FOR_CONFIDENCE = 30;

function closeReasonBreakdown(trades) {
  const counts = { SL: 0, TP: 0, TIME: 0, SIGNAL: 0, EOD: 0 };
  trades.forEach((t) => {
    if (counts[t.close_reason] !== undefined) counts[t.close_reason] += 1;
  });
  return counts;
}

function maxConsecutiveLosses(trades) {
  let max = 0;
  let current = 0;
  trades.forEach((t) => {
    if (t.profit <= 0) {
      current += 1;
      max = Math.max(max, current);
    } else {
      current = 0;
    }
  });
  return max;
}

function drawdownLabel(maxDrawdown) {
  if (maxDrawdown >= 30) return { label: "Élevé", tone: "danger" };
  if (maxDrawdown >= 15) return { label: "Modéré", tone: "warning" };
  return { label: "Faible", tone: "good" };
}

export function computeDiagnostic(results, strategy, config) {
  const { metrics, trades } = results;
  const { totalTrades, winRate, profitFactor, netProfit, avgWin, avgLoss, maxDrawdown } = metrics;

  const suggestions = [];

  // ── Verdict global ──────────────────────────────────────────────────
  let verdict, verdictTone;
  if (totalTrades === 0) {
    verdict = "Aucun trade déclenché sur cette période — impossible d'évaluer la stratégie.";
    verdictTone = "neutral";
    suggestions.push(
      "Vérifiez que les conditions d'entrée ne sont pas trop restrictives pour ce timeframe/cette période, ou testez une période plus longue."
    );
    return { verdict, verdictTone, suggestions, sampleWarning: null, exitBreakdown: null, breakevenWinRate: null, maxLosingStreak: null, drawdown: null };
  }
  if (profitFactor >= 1.3 && netProfit > 0) {
    verdict = "Rentable sur cette période.";
    verdictTone = "good";
  } else if (profitFactor >= 0.9) {
    verdict = "Quasi à l'équilibre — ni franchement rentable, ni franchement perdant.";
    verdictTone = "neutral";
  } else {
    verdict = "Perdant sur cette période.";
    verdictTone = "danger";
  }

  // ── Fiabilité de l'échantillon ──────────────────────────────────────
  const sampleWarning =
    totalTrades < MIN_TRADES_FOR_CONFIDENCE
      ? `Seulement ${totalTrades} trade(s) — en dessous de ${MIN_TRADES_FOR_CONFIDENCE}, les statistiques (taux de réussite, profit factor) ne sont pas fiables. Testez sur une période plus longue avant de tirer une conclusion.`
      : null;
  if (sampleWarning) suggestions.push("Élargissez la période testée pour obtenir un échantillon de trades plus fiable.");

  // ── Répartition des sorties ──────────────────────────────────────────
  const exitBreakdown = closeReasonBreakdown(trades);
  const slShare = totalTrades > 0 ? (exitBreakdown.SL / totalTrades) * 100 : 0;
  const tpShare = totalTrades > 0 ? (exitBreakdown.TP / totalTrades) * 100 : 0;
  if (slShare > 70 && winRate < 40) {
    suggestions.push(
      `${slShare.toFixed(0)}% des trades se terminent en stop-loss — le stop est probablement trop serré par rapport au mouvement normal du prix sur ce timeframe. Essayez un stop plus large (multiplicateur ATR plus élevé) ou ajoutez une condition de confirmation avant l'entrée.`
    );
  }
  if (tpShare < 10 && totalTrades >= MIN_TRADES_FOR_CONFIDENCE) {
    suggestions.push(
      `Seulement ${tpShare.toFixed(0)}% des trades atteignent le take-profit — l'objectif est peut-être trop ambitieux par rapport à la volatilité réelle de l'actif sur ce timeframe.`
    );
  }

  // ── Seuil de rentabilité ─────────────────────────────────────────────
  const breakevenWinRate = avgWin + avgLoss > 0 ? (avgLoss / (avgWin + avgLoss)) * 100 : null;
  if (breakevenWinRate !== null) {
    const gap = winRate - breakevenWinRate;
    if (gap < 0) {
      suggestions.push(
        `Le taux de réussite (${winRate.toFixed(1)}%) est en dessous du seuil de rentabilité pour ce ratio gain/perte moyen (${breakevenWinRate.toFixed(1)}%) — soit augmenter le taux de réussite (filtre d'entrée plus strict), soit améliorer le ratio gain/perte (stop plus serré ou take-profit plus large, en restant cohérent avec la volatilité réelle).`
      );
    }
  }

  // ── Rafale de pertes consécutives ────────────────────────────────────
  const maxLosingStreak = maxConsecutiveLosses(trades);
  if (maxLosingStreak >= 8) {
    suggestions.push(
      `Jusqu'à ${maxLosingStreak} pertes consécutives observées — vérifiez que le risque par trade actuel (${config?.riskPerTrade ?? "?"}%) reste supportable sur une série aussi longue.`
    );
  }

  // ── Drawdown ─────────────────────────────────────────────────────────
  const drawdown = { value: maxDrawdown, ...drawdownLabel(maxDrawdown) };
  if (drawdown.tone === "danger") {
    suggestions.push(
      `Drawdown maximum de ${maxDrawdown.toFixed(1)}% — réduisez le risque par trade ou le nombre de positions simultanées avant d'envisager un compte réel.`
    );
  }

  // ── Ratio R:R configuré vs comportement réel ────────────────────────
  const configuredSL = strategy?.exit_conditions?.stop_loss;
  const configuredTP = strategy?.exit_conditions?.take_profit;
  if (configuredSL?.type === configuredTP?.type && configuredSL?.value && configuredTP?.value) {
    const configuredRR = configuredTP.value / configuredSL.value;
    if (configuredRR < 1.2 && winRate < 55) {
      suggestions.push(
        `Le ratio take-profit/stop-loss configuré (${configuredRR.toFixed(2)}) est faible pour un taux de réussite de ${winRate.toFixed(1)}% — un ratio plus élevé réduirait le taux de réussite nécessaire pour être rentable.`
      );
    }
  }

  if (suggestions.length === 0) {
    suggestions.push("Aucun signal d'alerte évident dans ces résultats — les statistiques semblent cohérentes avec un fonctionnement normal de la stratégie.");
  }

  return { verdict, verdictTone, sampleWarning, exitBreakdown, breakevenWinRate, maxLosingStreak, drawdown, suggestions };
}
