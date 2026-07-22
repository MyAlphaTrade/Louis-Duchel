import React, { useEffect, useMemo, useState } from "react";
import { base44 } from "@/api/base44Client";
import { useAsset } from "@/lib/AssetContext";
import { useAlphaTradeConnection } from "@/lib/AlphaTradeConnectionContext";
import { useToast } from "@/components/ui/use-toast";
import { loadLiveContext, fetchLiveTick, evaluateLiveStep } from "@/lib/paperTradingEngine";
import PaperTradingConfig from "@/components/paperTrading/PaperTradingConfig";
import {
  Send,
  Zap,
  ShieldCheck,
  Loader2,
  TrendingUp,
  TrendingDown,
  MinusCircle,
  Link2,
  ExternalLink,
  CheckCircle2,
} from "lucide-react";

// Module 5 — Export Signaux : évalue une stratégie sur le dernier prix réel
// (même pipeline que le mode Live du Paper Trading — loadLiveContext/
// fetchLiveTick/evaluateLiveStep) et permet d'envoyer le signal obtenu
// (BUY/SELL) vers AlphaTrade. Strategy Lab ne calcule ni n'envoie jamais
// directement un ordre réel : AlphaTrade reçoit uniquement une direction et
// applique son propre calcul de lot/stop-loss/take-profit et ses propres
// garde-fous (mode réel, verrous de forfait) — voir Paramètres > Connexion
// AlphaTrade pour le détail de ce pont.

function actionBadge(action) {
  if (action === "BUY") {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-semibold">
        <TrendingUp className="w-3.5 h-3.5" /> BUY
      </span>
    );
  }
  if (action === "SELL") {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs font-semibold">
        <TrendingDown className="w-3.5 h-3.5" /> SELL
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-500/10 border border-slate-500/30 text-slate-400 text-xs font-semibold">
      <MinusCircle className="w-3.5 h-3.5" /> WAIT
    </span>
  );
}

export default function Signals() {
  const { assets } = useAsset();
  const { connected } = useAlphaTradeConnection();
  const { toast } = useToast();

  const [strategies, setStrategies] = useState([]);
  const [history, setHistory] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [config, setConfig] = useState({
    strategyId: "",
    assetSymbol: "",
    timeframe: "M15",
    initialCapital: 10000,
    riskPerTrade: 1,
    lotSize: 0.1,
    leverage: 100,
    spread: 0,
    commission: 0,
    slippage: 0,
  });

  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState(null);
  const [candidate, setCandidate] = useState(null); // { symbol, action, entry_price, stop_loss, take_profit, strategy_name, generated_at }
  const [exporting, setExporting] = useState(false);

  const loadHistory = () => {
    setLoadingHistory(true);
    base44.entities.Signal.list("-created_date", 100)
      .then(setHistory)
      .catch(() => {})
      .finally(() => setLoadingHistory(false));
  };

  useEffect(() => {
    base44.entities.Strategy.list("-created_date", 500)
      .then((data) => setStrategies(data.filter((s) => s.status !== "archived")))
      .catch(() => {});
    loadHistory();
  }, []);

  const strategy = useMemo(
    () => strategies.find((s) => s.id === config.strategyId) || null,
    [strategies, config.strategyId]
  );
  const asset = useMemo(
    () => assets.find((a) => a.symbol === config.assetSymbol) || null,
    [assets, config.assetSymbol]
  );

  const handleGenerate = async () => {
    if (!strategy || !asset) return;
    setGenerating(true);
    setGenError(null);
    setCandidate(null);
    try {
      const lookbackBars = await loadLiveContext(asset.symbol, config.timeframe);
      const tick = await fetchLiveTick(asset.symbol);
      const result = evaluateLiveStep({
        openTrade: null,
        lookbackBars,
        tick,
        strategy,
        asset,
        config,
      });
      if (result.action === "open") {
        setCandidate({
          symbol: asset.symbol,
          action: result.order.direction,
          entry_price: result.order.entry_price,
          stop_loss: result.order.stop_loss,
          take_profit: result.order.take_profit,
          strategy_name: strategy.name,
          generated_at: new Date().toISOString(),
        });
      } else {
        setCandidate({
          symbol: asset.symbol,
          action: "WAIT",
          strategy_name: strategy.name,
          generated_at: new Date().toISOString(),
        });
      }
    } catch (err) {
      setGenError(err.message || "Impossible de générer un signal.");
    } finally {
      setGenerating(false);
    }
  };

  const handleExport = async () => {
    if (!candidate || candidate.action === "WAIT") return;
    setExporting(true);
    let created = null;
    try {
      created = await base44.entities.Signal.create({
        strategy_id: strategy.id,
        symbol: candidate.symbol,
        action: candidate.action,
        entry_price: candidate.entry_price,
        stop_loss: candidate.stop_loss,
        take_profit: candidate.take_profit,
        notes: `Généré depuis Strategy Lab — ${candidate.strategy_name}`,
        exported: false,
      });
      await base44.alphatrade.sendSignal({
        symbol: candidate.symbol,
        action: candidate.action,
        entry_price: candidate.entry_price,
        stop_loss: candidate.stop_loss,
        take_profit: candidate.take_profit,
        strategy_name: candidate.strategy_name,
      });
      await base44.entities.Signal.update(created.id, {
        exported: true,
        exported_at: new Date().toISOString(),
      });
      toast({ title: "Signal exporté", description: `${candidate.action} ${candidate.symbol} envoyé à AlphaTrade.` });
      setCandidate(null);
      loadHistory();
    } catch (err) {
      toast({
        variant: "destructive",
        title: "Échec de l'export",
        description: err.message || "AlphaTrade n'a pas accepté le signal.",
      });
      loadHistory();
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="p-6 lg:p-10 max-w-6xl">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <Send className="w-4 h-4 text-amber-400/70" />
          <span className="text-xs font-bold text-amber-400/70 tracking-widest uppercase">Module 5</span>
        </div>
        <h2 className="text-3xl lg:text-4xl font-bold font-heading text-white tracking-tight">
          Export Signaux
        </h2>
        <p className="mt-2 text-slate-400 text-base max-w-2xl">
          Générez un signal BUY/SELL/WAIT à partir d'une stratégie évaluée sur le dernier prix réel, puis
          exportez-le vers AlphaTrade pour exécution.
        </p>
        <div className="mt-3 flex items-center gap-2 text-[11px] text-emerald-400/80">
          <ShieldCheck className="w-3.5 h-3.5" />
          Strategy Lab ne choisit que la direction (BUY/SELL) — le lot, le stop-loss et le take-profit réels
          restent entièrement calculés et validés par AlphaTrade.
        </div>
      </div>

      {!connected && (
        <div className="mb-6 flex items-center justify-between gap-3 px-4 py-3 rounded-xl bg-amber-500/5 border border-amber-500/20 text-amber-400 text-sm">
          <div className="flex items-center gap-2">
            <Link2 className="w-4 h-4 flex-shrink-0" />
            Non connecté à AlphaTrade — l'export sera bloqué tant que vous ne vous êtes pas connecté.
          </div>
          <a href="/settings" className="flex items-center gap-1 text-xs font-medium hover:text-amber-300 whitespace-nowrap">
            Aller à Paramètres <ExternalLink className="w-3 h-3" />
          </a>
        </div>
      )}

      <div className="mb-6">
        <PaperTradingConfig strategies={strategies} config={config} setConfig={setConfig} disabled={generating} />
      </div>

      <div className="flex flex-wrap items-center gap-3 mb-6">
        <button
          type="button"
          onClick={handleGenerate}
          disabled={!strategy || !asset || generating}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-[#0a0e17] font-semibold text-sm hover:from-amber-400 hover:to-amber-500 disabled:opacity-40 transition-all"
        >
          {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
          {generating ? "Génération…" : "Générer un signal"}
        </button>
        {genError && <span className="text-xs text-red-400">{genError}</span>}
      </div>

      {candidate && (
        <div className="mb-8 p-5 rounded-2xl bg-[#0d1220] border border-[#1a2332]">
          <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
            <div className="flex items-center gap-3">
              {actionBadge(candidate.action)}
              <span className="text-sm text-slate-300 font-medium">{candidate.symbol}</span>
              <span className="text-xs text-slate-500">{candidate.strategy_name}</span>
            </div>
            {candidate.action !== "WAIT" && (
              <button
                type="button"
                onClick={handleExport}
                disabled={exporting || !connected}
                className="flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-sm font-semibold hover:bg-emerald-500/20 disabled:opacity-40 transition-colors"
                title={!connected ? "Connectez-vous à AlphaTrade depuis Paramètres" : undefined}
              >
                {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                {exporting ? "Envoi…" : "Exporter vers AlphaTrade"}
              </button>
            )}
          </div>
          {candidate.action === "WAIT" ? (
            <p className="text-xs text-slate-500">Aucune condition d'entrée n'est remplie actuellement pour cette stratégie.</p>
          ) : (
            <div className="grid grid-cols-3 gap-4">
              <div>
                <p className="text-[10px] text-slate-600 uppercase tracking-wider mb-1">Entrée</p>
                <p className="text-sm text-white font-mono">{candidate.entry_price?.toFixed(2)}</p>
              </div>
              <div>
                <p className="text-[10px] text-slate-600 uppercase tracking-wider mb-1">Stop-loss</p>
                <p className="text-sm text-red-400 font-mono">{candidate.stop_loss?.toFixed(2)}</p>
              </div>
              <div>
                <p className="text-[10px] text-slate-600 uppercase tracking-wider mb-1">Take-profit</p>
                <p className="text-sm text-emerald-400 font-mono">{candidate.take_profit?.toFixed(2)}</p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Historique */}
      <div>
        <h3 className="text-sm font-semibold text-white mb-3">Historique des signaux</h3>
        <div className="rounded-2xl bg-[#0d1220] border border-[#1a2332] overflow-hidden">
          {loadingHistory ? (
            <div className="p-8 flex justify-center">
              <Loader2 className="w-5 h-5 animate-spin text-slate-600" />
            </div>
          ) : history.length === 0 ? (
            <p className="p-8 text-center text-sm text-slate-500">Aucun signal généré pour l'instant.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#1a2332] text-left text-[11px] text-slate-500 uppercase tracking-wider">
                    <th className="px-4 py-2.5">Date</th>
                    <th className="px-4 py-2.5">Symbole</th>
                    <th className="px-4 py-2.5">Action</th>
                    <th className="px-4 py-2.5">Entrée</th>
                    <th className="px-4 py-2.5">SL</th>
                    <th className="px-4 py-2.5">TP</th>
                    <th className="px-4 py-2.5">Statut</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((s) => (
                    <tr key={s.id} className="border-b border-[#1a2332]/60 last:border-0">
                      <td className="px-4 py-2.5 text-slate-400 text-xs whitespace-nowrap">
                        {s.created_date ? new Date(s.created_date).toLocaleString("fr-FR") : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-slate-300">{s.symbol}</td>
                      <td className="px-4 py-2.5">{actionBadge(s.action)}</td>
                      <td className="px-4 py-2.5 text-slate-400 font-mono text-xs">{s.entry_price?.toFixed?.(2) ?? "—"}</td>
                      <td className="px-4 py-2.5 text-slate-400 font-mono text-xs">{s.stop_loss?.toFixed?.(2) ?? "—"}</td>
                      <td className="px-4 py-2.5 text-slate-400 font-mono text-xs">{s.take_profit?.toFixed?.(2) ?? "—"}</td>
                      <td className="px-4 py-2.5">
                        {s.exported ? (
                          <span className="inline-flex items-center gap-1 text-emerald-400 text-xs">
                            <CheckCircle2 className="w-3.5 h-3.5" /> Exporté
                          </span>
                        ) : (
                          <span className="text-slate-600 text-xs">Non exporté</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
