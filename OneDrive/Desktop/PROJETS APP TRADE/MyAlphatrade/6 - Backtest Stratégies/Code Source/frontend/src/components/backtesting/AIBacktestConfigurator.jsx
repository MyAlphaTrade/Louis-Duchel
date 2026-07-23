import React, { useState } from "react";
import { base44 } from "@/api/base44Client";
import { useAISettings } from "@/lib/AISettingsContext";
import { useAsset } from "@/lib/AssetContext";
import { TIMEFRAMES } from "@/lib/assets";
import { Wand2, Loader2, Sparkles, AlertTriangle } from "lucide-react";

// Configure le backtest (strategie, actif, periode, capital, risque...) a
// partir d'une demande en langage naturel, en reutilisant le meme
// fournisseur/cle IA que AI Designer et Diagnostic. Ne genere jamais une
// NOUVELLE strategie -- ca reste le role d'AI Designer (Module 6) -- ce
// composant choisit seulement parmi les strategies deja existantes et
// remplit les parametres d'execution du backtest.
export default function AIBacktestConfigurator({ strategies, config, setConfig, onAutoRun }) {
  const { provider, isConfigured, settings } = useAISettings();
  const { assets } = useAsset();
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [explanation, setExplanation] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!prompt.trim() || !provider) return;
    setLoading(true);
    setError(null);
    setExplanation(null);

    try {
      const marketSummary = await base44.marketData.summary().catch(() => []);
      const activeAssets = assets.filter((a) => a.status === "active");

      const strategyList = strategies
        .map((s) => {
          const scope =
            s.asset_scope === "specific" ? (s.asset_symbols || []).join("/") : s.asset_scope;
          return `- id="${s.id}" nom="${s.name}" actifs=${scope} timeframe_principal=${s.primary_timeframe} type_marche=${s.market_profile?.market_type || "any"} volatilite=${s.market_profile?.volatility || "any"} statut=${s.status} description="${s.description || ""}"`;
        })
        .join("\n");

      const assetList = activeAssets.map((a) => `${a.symbol} (${a.name})`).join(", ");

      const dataAvailability = marketSummary
        .map((m) => `${m.symbol}/${m.timeframe}: ${m.count} bougies, du ${m.start} au ${m.end}`)
        .join("\n") || "Aucune donnée réelle importée pour l'instant.";

      const today = new Date().toISOString().split("T")[0];

      const systemPrompt = [
        "Tu configures un backtest pour AlphaTrade Strategy Lab à partir d'une demande en langage naturel.",
        "Tu NE crées JAMAIS de nouvelle stratégie — tu choisis uniquement parmi celles déjà listées ci-dessous. Si aucune ne correspond raisonnablement à la demande, mets \"strategyId\": null et explique pourquoi dans \"explanation\" (suggère d'utiliser AI Designer pour en créer une nouvelle).",
        `Stratégies disponibles :\n${strategyList || "(aucune)"}`,
        `Actifs actifs : ${assetList}.`,
        `Historique réel disponible :\n${dataAvailability}`,
        `Timeframes valides : ${TIMEFRAMES.join(", ")}.`,
        `Date du jour : ${today}.`,
        "Choisis une période (startDate/endDate) cohérente avec l'historique réel disponible ci-dessus pour l'actif/timeframe retenu — ne demande pas plus de jours que ce qui est réellement importé, sauf si l'utilisateur l'exige explicitement.",
        "Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant/après, sans balises markdown, respectant exactement ce schéma :",
        `{
  "strategyId": string | null,
  "assetSymbol": string,
  "timeframe": "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1",
  "startDate": "YYYY-MM-DD",
  "endDate": "YYYY-MM-DD",
  "initialCapital": number,
  "riskPerTrade": number,
  "lotSize": number,
  "leverage": number,
  "spread": number,
  "commission": number,
  "slippage": number,
  "explanation": string
}`,
        "\"explanation\" doit être en français, 2-3 phrases max, expliquant ce que tu as choisi et pourquoi.",
        "Valeurs par défaut raisonnables si non précisées par l'utilisateur : initialCapital=10000, riskPerTrade=1, lotSize=0.1, leverage=100, spread=0, commission=0, slippage=0.",
      ].join("\n\n");

      const result = await provider.generate({
        prompt,
        systemPrompt,
        params: settings.params,
        apiKey: settings.apiKey,
        model: settings.model,
      });

      const parsed = parseJSON(result?.content);
      if (!parsed) {
        setError("La réponse de l'IA n'a pas pu être interprétée. Reformulez votre demande.");
        return;
      }

      if (!parsed.strategyId || !strategies.some((s) => s.id === parsed.strategyId)) {
        setExplanation(parsed.explanation || "Aucune stratégie existante ne correspond à cette demande.");
        return;
      }

      const nextConfig = {
        ...config,
        strategyId: parsed.strategyId,
        assetSymbol: parsed.assetSymbol || config.assetSymbol,
        timeframe: TIMEFRAMES.includes(parsed.timeframe) ? parsed.timeframe : config.timeframe,
        startDate: parsed.startDate || config.startDate,
        endDate: parsed.endDate || config.endDate,
        initialCapital: Number(parsed.initialCapital) || config.initialCapital,
        riskPerTrade: Number(parsed.riskPerTrade) || config.riskPerTrade,
        lotSize: Number(parsed.lotSize) || config.lotSize,
        leverage: Number(parsed.leverage) || config.leverage,
        spread: Number(parsed.spread) || 0,
        commission: Number(parsed.commission) || 0,
        slippage: Number(parsed.slippage) || 0,
      };

      setExplanation(parsed.explanation || null);
      setConfig(nextConfig);
      onAutoRun(nextConfig);
    } catch (err) {
      setError(err.message || "Erreur lors de la configuration par l'IA.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-5 rounded-2xl bg-gradient-to-r from-violet-500/5 to-transparent border border-violet-500/20 mb-4">
      <div className="flex items-center gap-2 mb-3">
        <Wand2 className="w-4 h-4 text-violet-400" />
        <h3 className="text-sm font-bold text-white">Configuration par IA</h3>
        <span className="text-[10px] text-slate-600">— décrivez ce que vous voulez tester, l'IA configure et lance le backtest</span>
      </div>

      {!isConfigured ? (
        <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-amber-500/5 border border-amber-500/15">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
          <p className="text-[11px] text-amber-400/80">
            Aucune clé API configurée. <a href="/settings" className="underline hover:text-amber-300">Configurer l'IA →</a>
          </p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="flex flex-col sm:flex-row gap-2">
          <input
            type="text"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Ex: teste la meilleure stratégie de tendance sur l'or, sur les 3 derniers mois, risque 1%"
            className="flex-1 px-3 py-2.5 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-violet-500/40 transition-colors"
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading || !prompt.trim()}
            className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-gradient-to-r from-violet-500 to-violet-600 text-white font-semibold text-sm hover:from-violet-400 hover:to-violet-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all whitespace-nowrap"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            {loading ? "Configuration…" : "Configurer et lancer"}
          </button>
        </form>
      )}

      {error && <p className="mt-2 text-xs text-rose-400">⚠️ {error}</p>}
      {explanation && (
        <p className="mt-3 text-xs text-slate-300 bg-[#0a0e17] border border-[#1a2332] rounded-lg px-3 py-2">
          <Sparkles className="w-3 h-3 text-violet-400 inline mr-1.5" />
          {explanation}
        </p>
      )}
    </div>
  );
}

function parseJSON(text) {
  if (!text || typeof text !== "string") return null;
  const trimmed = text.trim();
  try {
    return JSON.parse(trimmed);
  } catch {
    const match = trimmed.match(/\{[\s\S]*\}/);
    if (match) {
      try {
        return JSON.parse(match[0]);
      } catch {
        return null;
      }
    }
    return null;
  }
}
