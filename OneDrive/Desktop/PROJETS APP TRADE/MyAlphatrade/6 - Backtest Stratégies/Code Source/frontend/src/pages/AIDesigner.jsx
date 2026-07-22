import React, { useState, useRef, useEffect } from "react";
import { useAISettings } from "@/lib/AISettingsContext";
import { getProvider, getAllProviders } from "@/lib/aiProviders";
import { useAsset } from "@/lib/AssetContext";
import { INDICATORS, OPERATORS } from "@/lib/indicators";
import ChatMessage from "@/components/ai-designer/ChatMessage";
import ChatInput from "@/components/ai-designer/ChatInput";
import StrategyPreview from "@/components/ai-designer/StrategyPreview";
import { BrainCircuit, Settings, ChevronDown, AlertTriangle } from "lucide-react";

const WELCOME_MESSAGE = {
  role: "assistant",
  content:
    "Bonjour ! Je suis votre assistant de conception de stratégies AlphaTrade.\n\nDécrivez votre idée de trading en langage naturel — par exemple : *« Je veux acheter l'or quand le RSI cass une résistance »* — et je vous aiderai à la transformer en une stratégie structurée, testable et optimisable.\n\nPlus votre description sera détaillée, plus la stratégie générée sera précise.",
  timestamp: new Date().toISOString(),
};

export default function AIDesigner() {
  const { settings, provider, isConfigured } = useAISettings();
  const { activeAssets } = useAsset();
  const [messages, setMessages] = useState([WELCOME_MESSAGE]);
  const [strategy, setStrategy] = useState(null);
  const [validation, setValidation] = useState(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [showProviderDropdown, setShowProviderDropdown] = useState(false);
  const scrollRef = useRef(null);
  const providers = getAllProviders();

  // Auto-scroll to bottom on new message
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isThinking]);

  const handleSend = async (text) => {
    const userMsg = { role: "user", content: text, timestamp: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg]);
    setIsThinking(true);

    if (!isConfigured || !provider) {
      setIsThinking(false);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            "Aucune clé API configurée. Rendez-vous dans **Paramètres IA** pour connecter un fournisseur (Anthropic ou OpenAI) avant de pouvoir discuter avec l'assistant.\n\n[Configurer l'IA →](/settings)",
          timestamp: new Date().toISOString(),
        },
      ]);
      return;
    }

    try {
      const assetList = activeAssets.map((a) => a.symbol).join(", ") || "aucun actif actif pour le moment";
      const systemPrompt =
        "Tu es un assistant qui aide à concevoir des stratégies de trading pour AlphaTrade Strategy Lab. " +
        "Réponds en français, de façon concise, en aidant l'utilisateur à préciser sa stratégie " +
        "(actif, indicateurs, conditions d'entrée/sortie, gestion du risque). " +
        `Actifs disponibles : ${assetList}.`;

      const result = await provider.generate({
        prompt: text,
        systemPrompt,
        params: settings.params,
        apiKey: settings.apiKey,
        model: settings.model,
      });

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: result?.content?.trim() || "(Réponse vide de l'IA.)",
          timestamp: new Date().toISOString(),
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `⚠️ ${err.message || "Une erreur est survenue lors de l'appel à l'IA."}`,
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsThinking(false);
    }
  };

  const handleGenerate = async () => {
    if (!isConfigured || !provider) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            "Aucune clé API configurée. Rendez-vous dans **Paramètres IA** avant de générer une stratégie.\n\n[Configurer l'IA →](/settings)",
          timestamp: new Date().toISOString(),
        },
      ]);
      return;
    }

    setIsGenerating(true);
    try {
      const conversation = messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => `${m.role === "user" ? "Utilisateur" : "Assistant"}: ${m.content}`)
        .join("\n");
      const assetList = activeAssets.map((a) => a.symbol).join(", ") || "XAUUSD";
      const indicatorIds = INDICATORS.map((i) => i.id).join(", ");
      const operatorIds = OPERATORS.map((o) => o.id).join(", ");

      const systemPrompt = [
        "Tu génères des stratégies de trading structurées pour AlphaTrade Strategy Lab, à partir d'une conversation en langage naturel avec l'utilisateur.",
        "Réponds UNIQUEMENT avec un objet JSON valide, sans aucun texte avant ni après, sans balises markdown (pas de ```), respectant EXACTEMENT ce schéma :",
        `{
  "name": string,
  "description": string,
  "asset_scope": "specific" | "category" | "all",
  "asset_symbols": string[],
  "primary_timeframe": "M1" | "M5" | "M15" | "H1" | "H4" | "D1",
  "market_profile": {
    "sessions": string[] (parmi: sydney, tokyo, london, new_york),
    "volatility": "low" | "medium" | "high" | "any",
    "market_type": "trend" | "range" | "breakout" | "any",
    "ideal_conditions": string
  },
  "entry_conditions": {
    "buy": [ { "id": string, "enabled": boolean, "indicator": string, "operator": string, "target_value": number, "target_indicator": string } ],
    "sell": [ { "id": string, "enabled": boolean, "indicator": string, "operator": string, "target_value": number, "target_indicator": string } ]
  },
  "exit_conditions": {
    "take_profit": { "type": "pips" | "percent" | "atr" | "indicator", "value": number },
    "stop_loss": { "type": "pips" | "percent" | "atr" | "indicator", "value": number },
    "break_even": { "enabled": boolean, "trigger_pips": number, "offset_pips": number },
    "trailing_stop": { "enabled": boolean, "type": "pips" | "atr" | "percent", "distance": number },
    "indicator_exit": { "enabled": boolean, "rule": string },
    "time_exit": { "enabled": boolean, "max_bars": number }
  },
  "risk_management": { "type": "fixed" | "percent" | "lots", "risk_value": number, "min_rr": number, "max_positions": number, "max_drawdown": number },
  "trading_hours_filter": { "enabled": boolean, "start_hour": number, "end_hour": number, "days": string[] (parmi mon,tue,wed,thu,fri,sat,sun) },
  "status": "draft"
}`,
        `Indicateurs valides pour le champ "indicator" (et "target_indicator") : ${indicatorIds}.`,
        `Opérateurs valides pour le champ "operator" : ${operatorIds}.`,
        `Actifs disponibles dans AlphaTrade : ${assetList}.`,
        "Si une information n'a pas été précisée par l'utilisateur, choisis une valeur par défaut raisonnable plutôt que de laisser le champ vide.",
      ].join("\n\n");

      const prompt = `Voici la conversation avec l'utilisateur au sujet de sa stratégie de trading :\n\n${conversation}\n\nGénère la stratégie structurée correspondante, au format JSON demandé, et rien d'autre.`;

      const result = await provider.generate({
        prompt,
        systemPrompt,
        params: settings.params,
        apiKey: settings.apiKey,
        model: settings.model,
      });

      const parsed = parseStrategyJSON(result?.content);
      if (!parsed) {
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: "La stratégie générée n'a pas pu être interprétée, réessayez ou reformulez votre demande.",
            timestamp: new Date().toISOString(),
          },
        ]);
        return;
      }

      setStrategy(parsed);
      setValidation(computeValidation(parsed));

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          announcement: "Stratégie générée",
          content:
            "J'ai généré une stratégie à partir de votre conversation. Vous pouvez consulter l'aperçu à droite et l'ajuster dans le Créateur de stratégies.",
          timestamp: new Date().toISOString(),
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `⚠️ ${err.message || "Erreur lors de la génération de la stratégie."}`,
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleNewConversation = () => {
    setMessages([{ ...WELCOME_MESSAGE, timestamp: new Date().toISOString() }]);
    setStrategy(null);
    setValidation(null);
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-6 lg:px-10 pt-6 lg:pt-10 pb-4 border-b border-[#1a2332]">
        <div className="flex items-center gap-2 mb-1">
          <BrainCircuit className="w-4 h-4 text-amber-400/70" />
          <span className="text-xs font-bold text-amber-400/70 tracking-widest uppercase">
            Module 6
          </span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-3xl lg:text-4xl font-bold font-heading text-white tracking-tight">
              AI Strategy Designer
            </h2>
            <p className="mt-1 text-slate-400 text-sm max-w-xl">
              Transformez vos idées de trading en stratégies structurées grâce à l'intelligence artificielle.
            </p>
          </div>

          {/* Provider selector */}
          <div className="relative hidden sm:block">
            <button
              onClick={() => setShowProviderDropdown(!showProviderDropdown)}
              className="flex items-center gap-2 px-3 py-2 rounded-xl bg-[#0d1220] border border-[#1a2332] text-xs font-medium text-slate-300 hover:border-[#2a3548] transition-colors"
            >
              <div className={`w-2 h-2 rounded-full ${isConfigured ? "bg-emerald-400" : "bg-amber-400"}`} />
              <span>{provider?.name || "—"}</span>
              <span className="text-slate-600">·</span>
              <span className="text-slate-500">{settings.model}</span>
              <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
            </button>

            {showProviderDropdown && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowProviderDropdown(false)} />
                <div className="absolute right-0 top-full mt-1 z-20 w-64 rounded-xl bg-[#0d1220] border border-[#1a2332] shadow-2xl py-1">
                  <p className="px-3 py-1.5 text-[9px] text-slate-600 uppercase tracking-wider">Fournisseur IA</p>
                  {providers.map((p) => (
                    <button
                      key={p.id}
                      onClick={() => { setShowProviderDropdown(false); }}
                      className={`w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors ${
                        p.id === settings.providerId
                          ? "bg-amber-500/10 text-amber-400"
                          : "text-slate-400 hover:bg-white/5"
                      }`}
                    >
                      <div className={`w-2 h-2 rounded-full ${p.id === settings.providerId ? "bg-amber-400" : "bg-slate-700"}`} />
                      <div className="flex-1">
                        <p className="font-medium">{p.name}</p>
                        <p className="text-[9px] text-slate-600">{p.models.length} modèle(s)</p>
                      </div>
                    </button>
                  ))}
                  <div className="border-t border-[#1a2332] mt-1 pt-1">
                    <a
                      href="/settings"
                      className="w-full flex items-center gap-2 px-3 py-2 text-xs text-slate-500 hover:text-amber-400 transition-colors"
                    >
                      <Settings className="w-3.5 h-3.5" />
                      Configurer l'IA
                    </a>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Not configured warning */}
        {!isConfigured && (
          <div className="mt-3 flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/15">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
            <p className="text-[11px] text-amber-400/80">
              Aucune clé API configurée. Les réponses sont simulées.{" "}
              <a href="/settings" className="underline hover:text-amber-300">Configurer l'IA →</a>
            </p>
          </div>
        )}
      </div>

      {/* Main content: chat + preview */}
      <div className="flex-1 flex min-h-0">
        {/* Chat panel */}
        <div className="flex-1 flex flex-col min-w-0">
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-6 space-y-4">
            {messages.map((msg, i) => (
              <ChatMessage key={i} message={msg} />
            ))}
            {isThinking && (
              <ChatMessage message={{ role: "assistant", thinking: true }} />
            )}
          </div>

          <ChatInput
            onSend={handleSend}
            onGenerate={handleGenerate}
            onNewConversation={handleNewConversation}
            disabled={isThinking}
            isGenerating={isGenerating}
          />
        </div>

        {/* Strategy preview panel */}
        <div className="hidden lg:flex w-80 xl:w-96 flex-shrink-0 border-l border-[#1a2332] bg-[#0a0e17] flex-col overflow-y-auto">
          <div className="px-4 py-3 border-b border-[#1a2332] flex items-center gap-2">
            <BrainCircuit className="w-4 h-4 text-amber-400/70" />
            <h3 className="text-xs font-bold text-white uppercase tracking-wider">Aperçu stratégie</h3>
          </div>
          <StrategyPreview strategy={strategy} validation={validation} isLoading={isGenerating} />
        </div>
      </div>
    </div>
  );
}

// ── Parsing & validation de la stratégie générée par l'IA ──────────────

/**
 * Parse la réponse texte du modèle en objet stratégie. Le modèle est
 * instruit de répondre uniquement avec du JSON, mais peut parfois entourer
 * sa réponse de texte ou de balises markdown — on tente donc d'extraire le
 * premier bloc `{...}` du texte avant d'abandonner.
 */
function parseStrategyJSON(text) {
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

function computeValidation(strategy) {
  const missingFields = [];
  const tp = strategy?.exit_conditions?.take_profit;
  const sl = strategy?.exit_conditions?.stop_loss;
  if (!tp || !tp.value) missingFields.push({ key: "take_profit", label: "Take Profit" });
  if (!sl || !sl.value) missingFields.push({ key: "stop_loss", label: "Stop Loss" });
  if (!strategy?.name) missingFields.push({ key: "name", label: "Nom de la stratégie" });
  if (strategy?.asset_scope === "specific" && !strategy?.asset_symbols?.length) {
    missingFields.push({ key: "asset_symbols", label: "Actif" });
  }
  return { isValid: missingFields.length === 0, missingFields };
}