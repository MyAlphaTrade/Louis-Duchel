import React, { useState, useEffect } from "react";
import { base44 } from "@/api/base44Client";
import { useAsset } from "@/lib/AssetContext";
import { useToast } from "@/components/ui/use-toast";
import BacktestConfig from "@/components/backtesting/BacktestConfig";
import BacktestResults from "@/components/backtesting/BacktestResults";
import SavedBacktests from "@/components/backtesting/SavedBacktests";
import { runBacktest } from "@/lib/backtestEngine";
import { FlaskConical, BarChart3, AlertTriangle, DatabaseZap } from "lucide-react";

function defaultDates() {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 90);
  return {
    startDate: start.toISOString().split("T")[0],
    endDate: end.toISOString().split("T")[0],
  };
}

export default function Backtesting() {
  const { assets } = useAsset();
  const { toast } = useToast();
  const [strategies, setStrategies] = useState([]);
  const [config, setConfig] = useState({
    strategyId: "",
    assetSymbol: "",
    timeframe: "M15",
    startDate: defaultDates().startDate,
    endDate: defaultDates().endDate,
    initialCapital: 10000,
    riskPerTrade: 1,
    lotSize: 0.1,
    spread: 0,
    commission: 0,
    slippage: 0,
    leverage: 100,
  });
  const [results, setResults] = useState(null);
  const [running, setRunning] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    base44.entities.Strategy.list("-created_date", 500)
      .then((data) => setStrategies(data.filter((s) => s.status !== "archived")))
      .catch(() => {});
  }, []);

  const handleRun = async () => {
    setRunning(true);
    setResults(null);
    setSaved(false);

    await new Promise((r) => setTimeout(r, 300));

    try {
      const strategy = strategies.find((s) => s.id === config.strategyId);
      const asset = assets.find((a) => a.symbol === config.assetSymbol);
      if (!strategy || !asset) return;

      const periodDays = Math.max(1, Math.ceil(
        (new Date(config.endDate) - new Date(config.startDate)) / 86400000
      ));

      const res = await runBacktest(strategy, asset, { ...config, periodDays });
      setResults({ ...res, strategy, asset });
    } catch (err) {
      toast({
        title: "Erreur",
        description: err.message || "Le backtest a échoué.",
        variant: "destructive",
      });
    } finally {
      setRunning(false);
    }
  };

  const handleSave = async () => {
    if (!results) return;
    try {
      const m = results.metrics;
      await base44.entities.BacktestResult.create({
        strategy_id: config.strategyId,
        start_date: config.startDate,
        end_date: config.endDate,
        total_trades: m.totalTrades,
        winning_trades: m.winningTrades,
        losing_trades: m.losingTrades,
        win_rate: m.winRate,
        total_profit: m.netProfit,
        max_drawdown: m.maxDrawdown,
        profit_factor: m.profitFactor,
        sharpe_ratio: 0,
        trades: results.trades.map((t) => ({
          type: t.direction,
          entry_price: t.entry_price,
          exit_price: t.exit_price,
          profit: t.profit,
          entry_time: t.entry_time?.toISOString?.() || t.entry_time,
          exit_time: t.exit_time?.toISOString?.() || t.exit_time,
        })),
      });
      await base44.entities.Strategy.update(config.strategyId, { status: "tested" });
      setSaved(true);
      toast({
        title: "Résultats sauvegardés",
        description: "Le backtest est enregistré et la stratégie marquée comme testée.",
      });
    } catch (err) {
      toast({
        title: "Erreur de sauvegarde",
        description: err.message,
        variant: "destructive",
      });
    }
  };

  return (
    <div className="p-6 lg:p-10 max-w-7xl">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <FlaskConical className="w-4 h-4 text-amber-400/70" />
          <span className="text-xs font-bold text-amber-400/70 tracking-widest uppercase">
            Module 3
          </span>
        </div>
        <h2 className="text-3xl lg:text-4xl font-bold font-heading text-white tracking-tight">
          Backtesting
        </h2>
        <p className="mt-2 text-slate-400 text-base max-w-xl">
          Testez vos stratégies sur des données historiques et analysez les performances avant de les connecter à AlphaTrade.
        </p>
      </div>

      {/* Config */}
      <BacktestConfig
        strategies={strategies}
        config={config}
        setConfig={setConfig}
        onRun={handleRun}
        running={running}
      />

      {/* Running state */}
      {running && (
        <div className="mt-6 flex flex-col items-center justify-center py-16 rounded-2xl bg-[#0d1220] border border-[#1a2332]">
          <div className="w-10 h-10 border-4 border-amber-500/20 border-t-amber-500 rounded-full animate-spin mb-4" />
          <p className="text-sm text-slate-400">Simulation en cours…</p>
          <p className="text-xs text-slate-600 mt-1">
            Génération des données · Calcul des indicateurs · Exécution des trades
          </p>
        </div>
      )}

      {/* Results */}
      {results && !running && (
        <div className="mt-6">
          {results.dataSource === "synthetic" && (
            <div className="mb-4 flex items-start gap-3 p-4 rounded-2xl bg-rose-500/10 border border-rose-500/30">
              <AlertTriangle className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-bold text-rose-300">Données simulées — résultats non fiables</p>
                <p className="text-xs text-rose-300/80 mt-0.5">
                  Ce backtest utilise des données simulées — importez l'historique réel de{" "}
                  {results.asset?.symbol} depuis Données de marché pour des résultats fiables.
                </p>
              </div>
            </div>
          )}
          {results.dataSource === "real" && results.warning && (
            <div className="mb-4 flex items-start gap-3 p-4 rounded-2xl bg-amber-500/10 border border-amber-500/30">
              <DatabaseZap className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-bold text-amber-300">Historique réel partiel</p>
                <p className="text-xs text-amber-300/80 mt-0.5">{results.warning}</p>
              </div>
            </div>
          )}
          <BacktestResults
            results={results}
            strategy={results.strategy}
            asset={results.asset}
            config={config}
            onSave={handleSave}
            saved={saved}
            strategies={strategies}
          />
        </div>
      )}

      {/* Empty state */}
      {!results && !running && (
        <div className="mt-6 space-y-4">
          <div className="text-center py-16 rounded-2xl bg-[#0d1220] border border-dashed border-[#1a2332]">
            <BarChart3 className="w-8 h-8 text-slate-700 mx-auto mb-3" />
            <p className="text-sm text-slate-500">
              Configurez votre backtest ci-dessus et lancez la simulation.
            </p>
          </div>
          <SavedBacktests strategies={strategies} />
        </div>
      )}
    </div>
  );
}