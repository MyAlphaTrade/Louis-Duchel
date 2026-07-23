import React, { useMemo, useState } from "react";
import { computeDiagnostic } from "@/lib/backtestDiagnostic";
import { useAISettings } from "@/lib/AISettingsContext";
import { ClipboardList, CheckCircle2, AlertTriangle, XCircle, Sparkles, Loader2 } from "lucide-react";

const TONE_STYLES = {
  good: { border: "border-emerald-500/30", bg: "bg-emerald-500/10", text: "text-emerald-400", Icon: CheckCircle2 },
  neutral: { border: "border-amber-500/30", bg: "bg-amber-500/10", text: "text-amber-400", Icon: AlertTriangle },
  danger: { border: "border-rose-500/30", bg: "bg-rose-500/10", text: "text-rose-400", Icon: XCircle },
};

function StatPill({ label, value }) {
  return (
    <div className="px-3 py-2 rounded-lg bg-[#0a0e17] border border-[#1a2332]">
      <p className="text-[9px] text-slate-600 uppercase tracking-wider">{label}</p>
      <p className="text-xs text-slate-300 font-mono mt-0.5">{value}</p>
    </div>
  );
}

// Diagnostic toujours affiche (deterministe, sans IA) — le bouton "Analyse IA"
// est une couche optionnelle en plus, jamais un remplacement : le verdict et
// les pistes d'ajustement ci-dessus restent valables meme sans cle API.
export default function BacktestDiagnostic({ results, strategy, config }) {
  const { provider, isConfigured, settings } = useAISettings();
  const diagnostic = useMemo(() => computeDiagnostic(results, strategy, config), [results, strategy, config]);
  const [aiText, setAiText] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState(null);

  const tone = TONE_STYLES[diagnostic.verdictTone] || TONE_STYLES.neutral;
  const { Icon } = tone;

  const handleAskAI = async () => {
    setAiLoading(true);
    setAiError(null);
    setAiText(null);
    try {
      const m = results.metrics;
      const summary = [
        `Stratégie: ${strategy?.name || "?"} sur ${config?.assetSymbol || "?"} (${config?.timeframe || "?"}).`,
        `Trades: ${m.totalTrades} (${m.winningTrades} gagnants / ${m.losingTrades} perdants), taux de réussite ${m.winRate}%.`,
        `Profit net: $${m.netProfit}, profit factor ${m.profitFactor}, drawdown max ${m.maxDrawdown}%.`,
        `Gain moyen $${m.avgWin} / perte moyenne $${m.avgLoss}, espérance $${m.expectancy} par trade.`,
        diagnostic.exitBreakdown
          ? `Sorties: ${diagnostic.exitBreakdown.SL} SL, ${diagnostic.exitBreakdown.TP} TP, ${diagnostic.exitBreakdown.TIME} time-exit, ${diagnostic.exitBreakdown.SIGNAL} signal.`
          : "",
        `Configuration de sortie: stop-loss ${JSON.stringify(strategy?.exit_conditions?.stop_loss)}, take-profit ${JSON.stringify(strategy?.exit_conditions?.take_profit)}.`,
        `Diagnostic déterministe déjà calculé: ${diagnostic.verdict} Pistes déjà identifiées: ${diagnostic.suggestions.join(" ")}`,
      ].filter(Boolean).join("\n");

      const systemPrompt =
        "Tu es un analyste quantitatif qui commente des résultats de backtest pour AlphaTrade Strategy Lab. " +
        "On te donne les statistiques déjà calculées et un diagnostic déterministe déjà produit par le système. " +
        "Ne recalcule aucun chiffre, ne les remets pas en question. Ton rôle: donner une lecture plus nuancée en 3-5 phrases " +
        "(pourquoi ces résultats sont plausibles, ce qui mérite le plus d'attention en premier) et 1-2 pistes d'ajustement concrètes " +
        "et actionnables dans l'éditeur de stratégie (indicateurs, périodes, type de sortie), en français, sans généralités vagues.";

      const result = await provider.generate({
        prompt: summary,
        systemPrompt,
        params: settings.params,
        apiKey: settings.apiKey,
        model: settings.model,
      });
      setAiText(result?.content?.trim() || "(Réponse vide de l'IA.)");
    } catch (err) {
      setAiError(err.message || "Erreur lors de l'appel à l'IA.");
    } finally {
      setAiLoading(false);
    }
  };

  return (
    <div className="rounded-2xl bg-[#0d1220] border border-[#1a2332] overflow-hidden">
      <div className="px-5 py-4 border-b border-[#1a2332] flex items-center gap-2">
        <ClipboardList className="w-4 h-4 text-amber-400/70" />
        <h3 className="text-sm font-bold text-white">Diagnostic</h3>
      </div>

      <div className="p-5 space-y-4">
        {/* Verdict */}
        <div className={`flex items-start gap-3 p-3 rounded-xl border ${tone.border} ${tone.bg}`}>
          <Icon className={`w-4 h-4 flex-shrink-0 mt-0.5 ${tone.text}`} />
          <p className={`text-sm font-medium ${tone.text}`}>{diagnostic.verdict}</p>
        </div>

        {diagnostic.sampleWarning && (
          <p className="text-xs text-slate-500">{diagnostic.sampleWarning}</p>
        )}

        {/* Stat pills */}
        {diagnostic.exitBreakdown && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <StatPill label="Sorties SL" value={diagnostic.exitBreakdown.SL} />
            <StatPill label="Sorties TP" value={diagnostic.exitBreakdown.TP} />
            <StatPill
              label="Seuil de rentabilité"
              value={diagnostic.breakevenWinRate !== null ? `${diagnostic.breakevenWinRate.toFixed(1)}%` : "—"}
            />
            <StatPill
              label="Pertes consécutives max"
              value={diagnostic.maxLosingStreak ?? "—"}
            />
          </div>
        )}

        {/* Suggestions */}
        <div>
          <p className="text-[10px] text-slate-600 uppercase tracking-wider mb-2">À ajuster</p>
          <ul className="space-y-2">
            {diagnostic.suggestions.map((s, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-slate-300">
                <span className="text-amber-400/60 mt-0.5">→</span>
                <span>{s}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* AI enhancement (optional) */}
        <div className="pt-3 border-t border-[#1a2332]">
          {!aiText && !aiLoading && (
            <button
              onClick={handleAskAI}
              disabled={!isConfigured}
              title={!isConfigured ? "Configurez un fournisseur IA dans Paramètres pour activer cette fonction." : undefined}
              className="flex items-center gap-2 px-3 py-2 rounded-xl bg-[#0a0e17] border border-[#1a2332] text-slate-400 text-xs font-medium hover:text-violet-400 hover:border-violet-500/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Sparkles className="w-3.5 h-3.5" />
              Analyse IA approfondie
            </button>
          )}
          {aiLoading && (
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Analyse en cours…
            </div>
          )}
          {aiError && <p className="text-xs text-rose-400">⚠️ {aiError}</p>}
          {aiText && (
            <div className="p-3 rounded-xl bg-violet-500/5 border border-violet-500/20">
              <div className="flex items-center gap-2 mb-2">
                <Sparkles className="w-3.5 h-3.5 text-violet-400" />
                <span className="text-[10px] text-violet-400 uppercase tracking-wider font-semibold">Analyse IA</span>
              </div>
              <p className="text-xs text-slate-300 whitespace-pre-line leading-relaxed">{aiText}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
