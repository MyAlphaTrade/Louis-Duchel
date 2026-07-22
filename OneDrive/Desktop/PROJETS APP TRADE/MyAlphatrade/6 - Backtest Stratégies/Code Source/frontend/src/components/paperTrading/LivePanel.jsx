import React, { useEffect, useRef, useState, useCallback } from "react";
import { base44 } from "@/api/base44Client";
import {
  loadLiveContext, fetchLiveTick, evaluateLiveStep, LIVE_POLL_INTERVAL_MS,
} from "@/lib/paperTradingEngine";
import {
  Play, Square, Radio, AlertTriangle, RefreshCw, TrendingUp, TrendingDown,
  Clock, Loader2, MonitorX,
} from "lucide-react";

function formatDateTime(d) {
  if (!d) return "—";
  return new Date(d).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDuration(fromIso, toIso) {
  if (!fromIso) return "—";
  const ms = new Date(toIso || Date.now()) - new Date(fromIso);
  const min = Math.max(0, Math.round(ms / 60000));
  if (min < 60) return `${min}min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}h${m > 0 ? m : ""}`;
}

// Convertit un PaperTrade persiste (forme DB) vers la forme interne attendue
// par les primitives du moteur (backtestEngine.js / paperTradingEngine.js).
function toEngineTrade(paperTrade) {
  if (!paperTrade) return null;
  return {
    direction: paperTrade.direction,
    entry_price: paperTrade.entry_price,
    stop_loss: paperTrade.stop_loss,
    take_profit: paperTrade.take_profit,
    volume: paperTrade.lot_size,
    entry_time: paperTrade.opened_at,
  };
}

export default function LivePanel({ strategy, asset, config }) {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [polling, setPolling] = useState(false);
  const [openTrade, setOpenTrade] = useState(null);
  const [unrealizedPnl, setUnrealizedPnl] = useState(0);
  const [lastTick, setLastTick] = useState(null);
  const [history, setHistory] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const lookbackRef = useRef(null);
  const intervalRef = useRef(null);
  const openTradeRef = useRef(null);
  openTradeRef.current = openTrade;

  const canStart = !!strategy && !!asset;

  const loadHistory = useCallback(async () => {
    if (!strategy) return;
    setLoadingHistory(true);
    try {
      const all = await base44.entities.PaperTrade.list("-created_date", 200);
      const mine = all.filter((t) => t.strategy_id === strategy.id && t.symbol === asset?.symbol);
      const open = mine.find((t) => t.status === "open") || null;
      const closed = mine.filter((t) => t.status === "closed");
      setOpenTrade(open);
      setHistory(closed);
    } catch {
      // Historique indisponible -- pas bloquant, l'utilisateur peut quand
      // meme demarrer le mode live.
    } finally {
      setLoadingHistory(false);
    }
  }, [strategy, asset?.symbol]);

  // Reset quand on change de strategie/actif : on arrete tout polling en
  // cours (les conditions evaluees ne correspondraient plus a la bonne
  // strategie) et on recharge l'historique du nouveau couple.
  useEffect(() => {
    stop();
    setError("");
    setLastTick(null);
    setUnrealizedPnl(0);
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategy?.id, asset?.symbol, config.timeframe]);

  useEffect(() => () => stop(), []); // cleanup on unmount

  const poll = useCallback(async () => {
    if (!strategy || !asset) return;
    setPolling(true);
    try {
      const tick = await fetchLiveTick(asset.symbol);
      setLastTick(tick);

      const decision = evaluateLiveStep({
        openTrade: toEngineTrade(openTradeRef.current),
        lookbackBars: lookbackRef.current,
        tick,
        strategy,
        asset,
        config,
      });

      if (decision.action === "open") {
        const created = await base44.entities.PaperTrade.create({
          strategy_id: strategy.id,
          symbol: asset.symbol,
          direction: decision.order.direction,
          entry_price: decision.order.entry_price,
          stop_loss: decision.order.stop_loss,
          take_profit: decision.order.take_profit,
          lot_size: decision.order.volume,
          status: "open",
          opened_at: new Date().toISOString(),
        });
        setOpenTrade(created);
        setUnrealizedPnl(0);
      } else if (decision.action === "close" && openTradeRef.current) {
        const current = openTradeRef.current;
        await base44.entities.PaperTrade.update(current.id, {
          exit_price: decision.trade.exit_price,
          profit_loss: decision.trade.profit,
          status: "closed",
          closed_at: new Date().toISOString(),
          close_reason: decision.trade.close_reason,
        });
        setOpenTrade(null);
        setUnrealizedPnl(0);
        loadHistory();
      } else if (decision.action === "hold") {
        setUnrealizedPnl(decision.unrealizedPnl);
      }
      setError("");
    } catch (err) {
      setError(err.message || "Erreur lors de la lecture du prix live.");
    } finally {
      setPolling(false);
    }
  }, [strategy, asset, config, loadHistory]);

  const start = async () => {
    if (!canStart) return;
    setError("");
    try {
      lookbackRef.current = await loadLiveContext(asset.symbol, config.timeframe);
    } catch (err) {
      setError(err.message || "Impossible de charger l'historique récent pour ce timeframe.");
      return;
    }
    setRunning(true);
    poll();
    intervalRef.current = setInterval(poll, LIVE_POLL_INTERVAL_MS);
  };

  function stop() {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    setRunning(false);
  }

  // "Réessayer" doit relancer ce qui a réellement échoué : si le contexte de
  // lookback n'a jamais été chargé avec succès (ex. premier "Démarrer" échoué
  // faute d'historique importé pour ce timeframe), il faut relancer start()
  // en entier — appeler poll() directement plante sur lookbackRef.current
  // toujours à null.
  const retry = () => (lookbackRef.current ? poll() : start());

  const mid = lastTick ? (lastTick.bid + lastTick.ask) / 2 : null;

  return (
    <div className="space-y-4">
      {/* Honesty banner */}
      <div className="flex items-start gap-3 p-4 rounded-2xl bg-amber-500/10 border border-amber-500/30">
        <MonitorX className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
        <div className="text-xs text-amber-300/90 leading-relaxed">
          <p className="font-bold text-amber-300">Ce mode ne fonctionne que pendant que cette page reste ouverte.</p>
          <p className="mt-0.5">
            Il n'y a pas de service en arrière-plan qui tourne 24/7 dans cette version : l'évaluation de la stratégie
            s'arrête dès que vous fermez ou quittez cet onglet. Nécessite un terminal <strong>MetaTrader 5 ouvert sur
            cette machine</strong> (lecture seule — aucun ordre réel n'est jamais envoyé).
          </p>
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center justify-between p-4 rounded-2xl bg-[#0d1220] border border-[#1a2332] flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <span className={`relative flex h-2.5 w-2.5 ${running ? "" : "opacity-40"}`}>
            {running && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />}
            <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${running ? "bg-emerald-400" : "bg-slate-600"}`} />
          </span>
          <div>
            <p className="text-sm font-bold text-white">
              {running ? "Live actif" : "Live arrêté"}
            </p>
            <p className="text-[10px] text-slate-500">
              {running
                ? `Vérification toutes les ${LIVE_POLL_INTERVAL_MS / 1000}s${polling ? " · lecture en cours…" : ""}`
                : "Aucune évaluation en cours"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {!running ? (
            <button
              onClick={start}
              disabled={!canStart}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-[#0a0e17] font-bold text-sm hover:from-amber-400 hover:to-amber-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              <Play className="w-4 h-4" />
              Démarrer
            </button>
          ) : (
            <button
              onClick={stop}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-400 font-bold text-sm hover:bg-rose-500/20 transition-all"
            >
              <Square className="w-4 h-4" />
              Arrêter
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-3 p-4 rounded-2xl bg-rose-500/10 border border-rose-500/30">
          <AlertTriangle className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="text-sm font-bold text-rose-300">Mode Live interrompu</p>
            <p className="text-xs text-rose-300/80 mt-0.5">{error}</p>
          </div>
          <button
            onClick={retry}
            disabled={polling}
            className="flex items-center gap-1.5 text-[10px] font-medium px-2.5 py-1.5 rounded-lg bg-[#0a0e17] border border-rose-500/20 text-rose-300 hover:bg-rose-500/10 disabled:opacity-50 transition-colors flex-shrink-0"
          >
            <RefreshCw className={`w-3 h-3 ${polling ? "animate-spin" : ""}`} />
            Réessayer
          </button>
        </div>
      )}

      {/* Last tick */}
      {lastTick && (
        <div className="flex items-center gap-4 px-4 py-3 rounded-2xl bg-[#0d1220] border border-[#1a2332] text-xs">
          <Radio className="w-3.5 h-3.5 text-amber-400" />
          <span className="text-slate-500">{asset?.symbol}</span>
          <span className="text-slate-300 font-mono">Bid {lastTick.bid?.toFixed(4)}</span>
          <span className="text-slate-300 font-mono">Ask {lastTick.ask?.toFixed(4)}</span>
          <span className="text-slate-600 ml-auto flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {formatDateTime(lastTick.timestamp)}
          </span>
        </div>
      )}

      {/* Open position */}
      <div className="p-5 rounded-2xl bg-[#0d1220] border border-[#1a2332]">
        <h3 className="text-sm font-bold text-white mb-3">Position ouverte</h3>
        {!openTrade ? (
          <p className="text-xs text-slate-600">Aucune position ouverte actuellement.</p>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-6 gap-4 items-center">
            <div>
              <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full ${
                openTrade.direction === "BUY" ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"
              }`}>
                {openTrade.direction === "BUY" ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                {openTrade.direction}
              </span>
            </div>
            <div>
              <span className="text-[9px] text-slate-600 uppercase tracking-wider block">Entrée</span>
              <span className="text-xs text-slate-300 font-mono">{openTrade.entry_price?.toFixed(4)}</span>
            </div>
            <div>
              <span className="text-[9px] text-slate-600 uppercase tracking-wider block">SL / TP</span>
              <span className="text-xs font-mono">
                <span className="text-rose-400">{openTrade.stop_loss?.toFixed(4)}</span>
                {" / "}
                <span className="text-emerald-400">{openTrade.take_profit?.toFixed(4)}</span>
              </span>
            </div>
            <div>
              <span className="text-[9px] text-slate-600 uppercase tracking-wider block">Lot</span>
              <span className="text-xs text-slate-300 font-mono">{openTrade.lot_size?.toFixed(2)}</span>
            </div>
            <div>
              <span className="text-[9px] text-slate-600 uppercase tracking-wider block">Ouverte depuis</span>
              <span className="text-xs text-slate-300">{formatDuration(openTrade.opened_at)}</span>
            </div>
            <div>
              <span className="text-[9px] text-slate-600 uppercase tracking-wider block">P&L flottant</span>
              <span className={`text-sm font-bold ${unrealizedPnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {unrealizedPnl >= 0 ? "+" : ""}${unrealizedPnl.toFixed(2)}
              </span>
            </div>
          </div>
        )}
        {mid && openTrade && (
          <p className="text-[10px] text-slate-600 mt-3">Prix actuel (mid) : {mid.toFixed(4)}</p>
        )}
      </div>

      {/* History */}
      <div className="rounded-2xl bg-[#0d1220] border border-[#1a2332] overflow-hidden">
        <div className="px-5 py-4 border-b border-[#1a2332] flex items-center justify-between">
          <h3 className="text-sm font-bold text-white">Historique des positions clôturées</h3>
          {loadingHistory && <Loader2 className="w-3.5 h-3.5 text-slate-600 animate-spin" />}
        </div>
        <div className="overflow-x-auto max-h-[360px] overflow-y-auto">
          <table className="w-full">
            <thead className="sticky top-0 bg-[#0d1220] z-10">
              <tr className="border-b border-[#1a2332]">
                <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2">Dir</th>
                <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2 hidden sm:table-cell">Ouverture</th>
                <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2 hidden md:table-cell">Entrée</th>
                <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2 hidden md:table-cell">Sortie</th>
                <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2">Motif</th>
                <th className="text-left text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2 hidden lg:table-cell">Durée</th>
                <th className="text-right text-[9px] font-semibold tracking-wider uppercase text-slate-600 px-3 py-2">P&L</th>
              </tr>
            </thead>
            <tbody>
              {history.map((t) => (
                <tr key={t.id} className="border-b border-[#1a2332] last:border-0 hover:bg-white/[0.02]">
                  <td className="px-3 py-2.5">
                    <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full ${
                      t.direction === "BUY" ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"
                    }`}>
                      {t.direction}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 hidden sm:table-cell text-xs text-slate-400">{formatDateTime(t.opened_at)}</td>
                  <td className="px-3 py-2.5 hidden md:table-cell text-xs text-slate-400 font-mono">{t.entry_price?.toFixed(4)}</td>
                  <td className="px-3 py-2.5 hidden md:table-cell text-xs text-slate-400 font-mono">{t.exit_price?.toFixed(4)}</td>
                  <td className="px-3 py-2.5 text-[10px] text-slate-500">{t.close_reason || "—"}</td>
                  <td className="px-3 py-2.5 hidden lg:table-cell text-xs text-slate-500">{formatDuration(t.opened_at, t.closed_at)}</td>
                  <td className="px-3 py-2.5 text-right">
                    <span className={`text-xs font-bold ${t.profit_loss >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {t.profit_loss >= 0 ? "+" : ""}${t.profit_loss?.toFixed(2)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {history.length === 0 && !loadingHistory && (
            <div className="py-8 text-center">
              <p className="text-xs text-slate-600">Aucune position clôturée pour l'instant.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
