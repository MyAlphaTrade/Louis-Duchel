import React, { useState } from "react";
import SummaryStats from "@/components/backtesting/SummaryStats";
import BacktestDiagnostic from "@/components/backtesting/BacktestDiagnostic";
import { computeDiagnostic } from "@/lib/backtestDiagnostic";
import EquityCurve from "@/components/backtesting/EquityCurve";
import TradeJournal from "@/components/backtesting/TradeJournal";
import Optimizer from "@/components/backtesting/Optimizer";
import BacktestComparison from "@/components/backtesting/BacktestComparison";
import MonteCarloAnalysis from "@/components/backtesting/MonteCarloAnalysis";
import { exportBacktestPDF } from "@/lib/exportPdf";
import { Save, CheckCircle2, FileDown, Sliders, Loader2, GitCompare, Dice5 } from "lucide-react";

export default function BacktestResults({ results, strategy, asset, config, onSave, saved, strategies }) {
  const { metrics, equityCurve, trades, bars, dataSource } = results;
  const [showOptimizer, setShowOptimizer] = useState(false);
  const [showComparison, setShowComparison] = useState(false);
  const [showMonteCarlo, setShowMonteCarlo] = useState(false);
  const [exporting, setExporting] = useState(false);

  const handleExportPDF = async () => {
    setExporting(true);
    try {
      const diagnostic = computeDiagnostic(results, strategy, config);
      await exportBacktestPDF(results, strategy, asset, config, diagnostic);
    } catch (err) {
      console.error(err);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between p-4 rounded-2xl bg-gradient-to-r from-amber-500/10 to-transparent border border-amber-500/20">
        <div>
          <h3 className="text-lg font-bold text-white">{strategy.name}</h3>
          <p className="text-xs text-slate-400 mt-0.5">
            {asset.symbol} · {config.timeframe} · {bars} bars
          </p>
          <div className="flex flex-wrap gap-2 mt-2">
            <span className="text-[9px] text-slate-500 px-2 py-0.5 rounded bg-white/5">
              Spread {config.spread} pips
            </span>
            <span className="text-[9px] text-slate-500 px-2 py-0.5 rounded bg-white/5">
              Commission ${config.commission}/lot
            </span>
            <span className="text-[9px] text-slate-500 px-2 py-0.5 rounded bg-white/5">
              Slippage {config.slippage} pips
            </span>
            <span className="text-[9px] text-slate-500 px-2 py-0.5 rounded bg-white/5">
              Levier 1:{config.leverage}
            </span>
            <span className="text-[9px] text-slate-500 px-2 py-0.5 rounded bg-white/5">
              Risque {config.riskPerTrade}%
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => { setShowComparison(!showComparison); setShowMonteCarlo(false); setShowOptimizer(false); }}
            className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-xs font-medium transition-colors ${
              showComparison
                ? "bg-amber-500/10 border-amber-500/20 text-amber-400"
                : "bg-[#0d1220] border-[#1a2332] text-slate-400 hover:text-amber-400 hover:border-amber-500/20"
            }`}
          >
            <GitCompare className="w-3.5 h-3.5" />
            Comparer
          </button>
          <button
            onClick={() => { setShowMonteCarlo(!showMonteCarlo); setShowComparison(false); setShowOptimizer(false); }}
            className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-xs font-medium transition-colors ${
              showMonteCarlo
                ? "bg-violet-500/10 border-violet-500/20 text-violet-400"
                : "bg-[#0d1220] border-[#1a2332] text-slate-400 hover:text-violet-400 hover:border-violet-500/20"
            }`}
          >
            <Dice5 className="w-3.5 h-3.5" />
            Monte Carlo
          </button>
          <button
            onClick={() => { setShowOptimizer(!showOptimizer); setShowComparison(false); setShowMonteCarlo(false); }}
            className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-xs font-medium transition-colors ${
              showOptimizer
                ? "bg-blue-500/10 border-blue-500/20 text-blue-400"
                : "bg-[#0d1220] border-[#1a2332] text-slate-400 hover:text-blue-400 hover:border-blue-500/20"
            }`}
          >
            <Sliders className="w-3.5 h-3.5" />
            Optimiser
          </button>
          <button
            onClick={handleExportPDF}
            disabled={exporting}
            className="flex items-center gap-2 px-3 py-2 rounded-xl bg-[#0d1220] border border-[#1a2332] text-slate-400 text-xs font-medium hover:text-blue-400 hover:border-blue-500/20 disabled:opacity-50 transition-colors"
          >
            {exporting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileDown className="w-3.5 h-3.5" />}
            {exporting ? "Export…" : "PDF"}
          </button>
          <button
            onClick={onSave}
            disabled={saved}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[#0d1220] border border-amber-500/20 text-amber-400 text-xs font-medium hover:bg-amber-500/5 disabled:opacity-50 transition-colors"
          >
            {saved ? <CheckCircle2 className="w-3.5 h-3.5" /> : <Save className="w-3.5 h-3.5" />}
            {saved ? "Sauvegardé" : "Sauvegarder"}
          </button>
        </div>
      </div>

      {/* Summary stats */}
      <SummaryStats metrics={{ ...metrics, bars }} />

      {/* Diagnostic — verdict + pistes d'ajustement, toujours disponible */}
      <BacktestDiagnostic results={results} strategy={strategy} config={config} />

      {/* Equity curve */}
      <EquityCurve equityCurve={equityCurve} initialCapital={config.initialCapital} />

      {/* Comparison */}
      {showComparison && (
        <BacktestComparison
          strategies={strategies || []}
          currentResult={{
            strategy_id: config.strategyId,
            start_date: config.startDate,
            end_date: config.endDate,
            total_trades: metrics.totalTrades,
            winning_trades: metrics.winningTrades,
            losing_trades: metrics.losingTrades,
            win_rate: metrics.winRate,
            total_profit: metrics.netProfit,
            max_drawdown: metrics.maxDrawdown,
            profit_factor: metrics.profitFactor,
          }}
          onClose={() => setShowComparison(false)}
        />
      )}

      {/* Monte Carlo */}
      {showMonteCarlo && (
        <MonteCarloAnalysis
          strategy={strategy}
          asset={asset}
          config={config}
          trades={trades}
          dataSource={dataSource}
          onClose={() => setShowMonteCarlo(false)}
        />
      )}

      {/* Optimizer */}
      {showOptimizer && (
        <Optimizer
          strategy={strategy}
          asset={asset}
          config={config}
          onClose={() => setShowOptimizer(false)}
        />
      )}

      {/* Trade journal */}
      <TradeJournal trades={trades} />
    </div>
  );
}