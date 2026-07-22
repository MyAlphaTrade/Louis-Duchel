import React, { useEffect, useRef, useState } from "react";
import {
  createReplaySession, initReplayState, stepReplay, fastForwardReplay,
  replayStateToResult, REPLAY_SPEEDS,
} from "@/lib/paperTradingEngine";
import SummaryStats from "@/components/backtesting/SummaryStats";
import EquityCurve from "@/components/backtesting/EquityCurve";
import TradeJournal from "@/components/backtesting/TradeJournal";
import {
  Play, Pause, SkipForward, RotateCcw, AlertTriangle, Film, TrendingUp, TrendingDown, Loader2,
} from "lucide-react";

export default function ReplayPanel({ strategy, asset, config }) {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [replayState, setReplayState] = useState(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState("5x");

  const sessionRef = useRef(null);
  const intervalRef = useRef(null);

  const canStart = !!strategy && !!asset;

  // Toute nouvelle selection invalide le rejeu en cours.
  useEffect(() => {
    stopInterval();
    setReplayState(null);
    setIsPlaying(false);
    setError("");
    sessionRef.current = null;
  }, [strategy?.id, asset?.symbol, config.timeframe]);

  useEffect(() => () => stopInterval(), []);

  function stopInterval() {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }

  // (Re)demarre l'intervalle d'animation a la vitesse courante.
  useEffect(() => {
    if (!isPlaying || !sessionRef.current) return;
    stopInterval();
    intervalRef.current = setInterval(() => {
      setReplayState((prev) => {
        if (!prev || prev.done) return prev;
        const next = stepReplay(prev, sessionRef.current);
        if (next.done) {
          setIsPlaying(false);
          stopInterval();
        }
        return next;
      });
    }, REPLAY_SPEEDS[speed] || REPLAY_SPEEDS["5x"]);
    return stopInterval;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPlaying, speed]);

  const handleStart = async () => {
    if (!canStart) return;
    setError("");
    setLoading(true);
    try {
      const session = await createReplaySession(strategy, asset, config);
      sessionRef.current = session;
      setReplayState(initReplayState(session.capital));
      setIsPlaying(true);
    } catch (err) {
      setError(err.message || "Impossible de charger l'historique pour ce rejeu.");
    } finally {
      setLoading(false);
    }
  };

  const handleTogglePlay = () => {
    if (!replayState || replayState.done) return;
    setIsPlaying((p) => !p);
  };

  const handleSkipToEnd = () => {
    if (!sessionRef.current) return;
    setIsPlaying(false);
    stopInterval();
    setReplayState(fastForwardReplay(sessionRef.current));
  };

  const handleReset = () => {
    stopInterval();
    setIsPlaying(false);
    setReplayState(null);
    sessionRef.current = null;
  };

  const total = sessionRef.current?.bars.length || 0;
  const progress = replayState && total > 0 ? Math.min(100, (replayState.i / total) * 100) : 0;
  const result = replayState && sessionRef.current ? replayStateToResult(replayState, sessionRef.current) : null;

  return (
    <div className="space-y-4">
      {/* Honesty banner */}
      <div className="flex items-start gap-3 p-4 rounded-2xl bg-violet-500/10 border border-violet-500/30">
        <Film className="w-5 h-5 text-violet-400 flex-shrink-0 mt-0.5" />
        <div className="text-xs text-violet-300/90 leading-relaxed">
          <p className="font-bold text-violet-300">Rejeu de l'historique déjà importé, bougie par bougie.</p>
          <p className="mt-0.5">
            La stratégie est évaluée pas à pas sur des données déjà connues (pas de prix en direct) — c'est un moyen
            de visualiser le comportement de la stratégie dans le temps plutôt qu'un résultat instantané. Le résultat
            final est identique à un backtest classique sur la même période.
          </p>
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center justify-between p-4 rounded-2xl bg-[#0d1220] border border-[#1a2332] flex-wrap gap-3">
        {!replayState ? (
          <>
            <p className="text-xs text-slate-500">Configurez la stratégie et l'actif ci-dessus, puis lancez le rejeu.</p>
            <button
              onClick={handleStart}
              disabled={!canStart || loading}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-[#0a0e17] font-bold text-sm hover:from-amber-400 hover:to-amber-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              {loading ? "Chargement…" : "Lancer le rejeu"}
            </button>
          </>
        ) : (
          <>
            <div className="flex items-center gap-3 flex-1 min-w-[200px]">
              <button
                onClick={handleTogglePlay}
                disabled={replayState.done}
                className="flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs font-bold hover:bg-amber-500/20 disabled:opacity-40 transition-colors"
              >
                {isPlaying ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                {isPlaying ? "Pause" : replayState.done ? "Terminé" : "Reprendre"}
              </button>
              <div className="flex-1">
                <div className="h-1.5 rounded-full bg-[#0a0e17] overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-amber-500 to-amber-400 transition-all" style={{ width: `${progress}%` }} />
                </div>
                <p className="text-[10px] text-slate-600 mt-1">
                  Bougie {replayState.i} / {total} ({progress.toFixed(0)}%)
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <select
                value={speed}
                onChange={(e) => setSpeed(e.target.value)}
                disabled={replayState.done}
                className="px-2.5 py-2 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-slate-300 text-xs focus:outline-none focus:border-amber-500/30 disabled:opacity-40"
              >
                {Object.keys(REPLAY_SPEEDS).map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <button
                onClick={handleSkipToEnd}
                disabled={replayState.done}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-[#0a0e17] border border-[#1a2332] text-slate-400 text-xs font-medium hover:text-blue-400 hover:border-blue-500/20 disabled:opacity-40 transition-colors"
              >
                <SkipForward className="w-3.5 h-3.5" />
                Aller à la fin
              </button>
              <button
                onClick={handleReset}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-[#0a0e17] border border-[#1a2332] text-slate-400 text-xs font-medium hover:text-rose-400 hover:border-rose-500/20 transition-colors"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                Recommencer
              </button>
            </div>
          </>
        )}
      </div>

      {error && (
        <div className="flex items-start gap-3 p-4 rounded-2xl bg-rose-500/10 border border-rose-500/30">
          <AlertTriangle className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-bold text-rose-300">Rejeu impossible</p>
            <p className="text-xs text-rose-300/80 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {replayState && replayState.openTrade && (
        <div className="p-5 rounded-2xl bg-[#0d1220] border border-[#1a2332]">
          <h3 className="text-sm font-bold text-white mb-3">Position ouverte à cet instant du rejeu</h3>
          <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-4 items-center">
            <div>
              <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full ${
                replayState.openTrade.direction === "BUY" ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"
              }`}>
                {replayState.openTrade.direction === "BUY" ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                {replayState.openTrade.direction}
              </span>
            </div>
            <div>
              <span className="text-[9px] text-slate-600 uppercase tracking-wider block">Entrée</span>
              <span className="text-xs text-slate-300 font-mono">{replayState.openTrade.entry_price?.toFixed(4)}</span>
            </div>
            <div>
              <span className="text-[9px] text-slate-600 uppercase tracking-wider block">SL / TP</span>
              <span className="text-xs font-mono">
                <span className="text-rose-400">{replayState.openTrade.stop_loss?.toFixed(4)}</span>
                {" / "}
                <span className="text-emerald-400">{replayState.openTrade.take_profit?.toFixed(4)}</span>
              </span>
            </div>
            <div>
              <span className="text-[9px] text-slate-600 uppercase tracking-wider block">Lot</span>
              <span className="text-xs text-slate-300 font-mono">{replayState.openTrade.volume?.toFixed(2)}</span>
            </div>
            <div>
              <span className="text-[9px] text-slate-600 uppercase tracking-wider block">Équité courante</span>
              <span className="text-sm font-bold text-amber-400">${replayState.equity.toFixed(2)}</span>
            </div>
          </div>
        </div>
      )}

      {result && result.trades.length + result.equityCurve.length > 0 && (
        <div className="space-y-4">
          <SummaryStats metrics={{ ...result.metrics, bars: result.bars }} />
          <EquityCurve equityCurve={result.equityCurve} initialCapital={sessionRef.current.capital} />
          <TradeJournal trades={result.trades} />
        </div>
      )}
    </div>
  );
}
