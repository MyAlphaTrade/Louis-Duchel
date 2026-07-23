import React, { useState } from "react";
import { base44 } from "@/api/base44Client";
import { useAISettings } from "@/lib/AISettingsContext";
import { useAsset } from "@/lib/AssetContext";
import { TIMEFRAMES } from "@/lib/assets";
import { INDICATORS, OPERATORS } from "@/lib/indicators";
import { Wand2, Loader2, Sparkles, AlertTriangle, PlusCircle } from "lucide-react";

// Configure (et lance) un backtest a partir d'une demande en langage
// naturel, en reutilisant le meme fournisseur/cle IA que AI Designer et
// Diagnostic. L'IA peut soit choisir une strategie EXISTANTE, soit en
// CONCEVOIR une nouvelle si rien de ce qui existe deja ne correspond a la
// demande -- meme schema JSON que AI Designer (Module 6), pour rester
// compatible avec le createur de strategies et le moteur de backtest.
export default function AIBacktestConfigurator({ strategies, config, setConfig, onAutoRun, onStrategyCreated }) {
  const { provider, isConfigured, settings } = useAISettings();
  const { assets } = useAsset();
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [explanation, setExplanation] = useState(null);
  const [createdStrategyName, setCreatedStrategyName] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!prompt.trim() || !provider) return;
    setLoading(true);
    setError(null);
    setExplanation(null);
    setCreatedStrategyName(null);

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
      const indicatorIds = INDICATORS.map((i) => i.id).join(", ");
      const operatorIds = OPERATORS.map((o) => o.id).join(", ");

      const systemPrompt = [
        "Tu configures et lances un backtest pour AlphaTrade Strategy Lab à partir d'une demande en langage naturel.",
        "Deux options selon la demande :",
        "1) Une stratégie déjà existante (listée ci-dessous) correspond raisonnablement bien → utilise son id dans \"strategyId\", laisse \"newStrategy\" à null.",
        "2) Aucune ne correspond, ou l'utilisateur décrit explicitement une logique d'entrée/sortie spécifique → conçois une NOUVELLE stratégie complète dans \"newStrategy\" (structurée, avec de vraies conditions basées sur les indicateurs listés plus bas), laisse \"strategyId\" à null.",
        "Ne fais JAMAIS les deux à la fois. Ne laisse jamais les deux à null sauf si la demande est authentiquement impossible à satisfaire (explique pourquoi dans ce cas).",
        `Stratégies existantes :\n${strategyList || "(aucune)"}`,
        `Actifs actifs : ${assetList}.`,
        `Historique réel disponible :\n${dataAvailability}`,
        `Timeframes valides : ${TIMEFRAMES.join(", ")}.`,
        `Date du jour : ${today}.`,
        `Indicateurs valides pour "indicator"/"target_indicator" (dans newStrategy) : ${indicatorIds}.`,
        `Opérateurs valides pour "operator" (dans newStrategy) : ${operatorIds}.`,
        "Choisis une période (startDate/endDate) cohérente avec l'historique réel disponible ci-dessus pour l'actif/timeframe retenu — ne demande pas plus de jours que ce qui est réellement importé, sauf si l'utilisateur l'exige explicitement.",
        "Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant/après, sans balises markdown, respectant exactement ce schéma :",
        `{
  "strategyId": string | null,
  "newStrategy": {
    "name": string,
    "description": string,
    "asset_scope": "specific",
    "asset_symbols": string[],
    "primary_timeframe": "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1",
    "market_profile": { "sessions": string[], "volatility": "low" | "medium" | "high" | "any", "market_type": "trend" | "range" | "breakout" | "any", "ideal_conditions": string },
    "entry_conditions": {
      "buy": [ { "indicator": string, "params": object, "operator": string, "target_indicator": string | null, "target_params": object | null, "target_value": number | null, "enabled": true } ],
      "sell": [ { "indicator": string, "params": object, "operator": string, "target_indicator": string | null, "target_params": object | null, "target_value": number | null, "enabled": true } ]
    },
    "exit_conditions": {
      "take_profit": { "type": "atr", "value": number, "params": null },
      "stop_loss": { "type": "atr", "value": number, "params": null },
      "break_even": { "enabled": false, "trigger_pips": 0, "offset_pips": 0 },
      "trailing_stop": { "enabled": false, "type": "pips", "distance": 10 },
      "indicator_exit": { "enabled": false, "rule": "" },
      "time_exit": { "enabled": false, "max_bars": 60 }
    },
    "risk_management": { "type": "percent", "risk_value": number, "min_rr": number, "max_positions": 1, "max_drawdown": 5 },
    "status": "draft"
  } | null,
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
        "IMPORTANT sur les conditions: \"greater_than\"/\"less_than\"/\"equals\"/\"crosses_above_level\"/\"crosses_below_level\" utilisent UNIQUEMENT target_value (jamais target_indicator). \"crosses_above\"/\"crosses_below\" utilisent UNIQUEMENT target_indicator (jamais target_value). Toujours utiliser \"atr\" comme type de stop_loss/take_profit (jamais \"pips\", qui est mal calibré pour XAUUSD).",
        "\"explanation\" doit être en français, 2-4 phrases max, expliquant ce que tu as choisi ou conçu et pourquoi.",
        "Valeurs par défaut raisonnables si non précisées : initialCapital=10000, riskPerTrade=1, lotSize=0.1, leverage=100, spread=0, commission=0, slippage=0.",
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

      let strategyId = parsed.strategyId && strategies.some((s) => s.id === parsed.strategyId)
        ? parsed.strategyId
        : null;
      let newlyCreated = null;

      if (!strategyId && parsed.newStrategy) {
        const invalid = validateNewStrategy(parsed.newStrategy);
        if (invalid) {
          setError(`Stratégie générée invalide : ${invalid}`);
          return;
        }
        newlyCreated = await base44.entities.Strategy.create(parsed.newStrategy);
        strategyId = newlyCreated.id;
        setCreatedStrategyName(newlyCreated.name);
        // Fait connaitre la nouvelle strategie au parent pour que son état
        // `strategies` l'inclue (dropdown, futurs runs) -- mais l'etat React
        // ne sera pas a jour avant le prochain rendu, donc onAutoRun
        // ci-dessous recoit aussi l'objet directement pour ne pas dependre
        // de ce timing.
        onStrategyCreated?.(newlyCreated);
      }

      if (!strategyId) {
        setExplanation(parsed.explanation || "Aucune stratégie ne correspond à cette demande.");
        return;
      }

      const nextConfig = {
        ...config,
        strategyId,
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
      onAutoRun(nextConfig, newlyCreated);
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
        <span className="text-[10px] text-slate-600">— décrivez ce que vous voulez tester, l'IA conçoit une stratégie si besoin, configure et lance le backtest</span>
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
            placeholder="Ex: je veux acheter l'or quand le RSI sort de survente sous la moyenne 200, avec un stop serré"
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
      {createdStrategyName && (
        <p className="mt-3 flex items-center gap-2 text-xs text-emerald-400 bg-emerald-500/5 border border-emerald-500/20 rounded-lg px-3 py-2">
          <PlusCircle className="w-3.5 h-3.5 flex-shrink-0" />
          Nouvelle stratégie créée : « {createdStrategyName} » (visible dans le Créateur de stratégies, statut brouillon).
        </p>
      )}
      {explanation && (
        <p className="mt-3 text-xs text-slate-300 bg-[#0a0e17] border border-[#1a2332] rounded-lg px-3 py-2">
          <Sparkles className="w-3 h-3 text-violet-400 inline mr-1.5" />
          {explanation}
        </p>
      )}
    </div>
  );
}

function validateNewStrategy(s) {
  if (!s.name) return "nom manquant.";
  if (!s.entry_conditions?.buy?.length && !s.entry_conditions?.sell?.length) {
    return "aucune condition d'entrée (buy/sell vides).";
  }
  if (!s.exit_conditions?.stop_loss?.value || !s.exit_conditions?.take_profit?.value) {
    return "stop-loss ou take-profit manquant.";
  }
  return null;
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
