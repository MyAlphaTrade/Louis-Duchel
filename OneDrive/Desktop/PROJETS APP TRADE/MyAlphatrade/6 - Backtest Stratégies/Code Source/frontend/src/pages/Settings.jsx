import React, { useState } from "react";
import { useAISettings } from "@/lib/AISettingsContext";
import { useAlphaTradeConnection } from "@/lib/AlphaTradeConnectionContext";
import { getAllProviders, getProvider, AI_PARAM_DEFAULTS } from "@/lib/aiProviders";
import {
  Settings as SettingsIcon,
  Eye,
  EyeOff,
  ExternalLink,
  Loader2,
  CheckCircle2,
  XCircle,
  Save,
  Link2,
  Unlink,
} from "lucide-react";

const inputCls =
  "w-full px-3 py-2 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40 transition-colors";

function Field({ label, hint, children }) {
  return (
    <div>
      <label className="text-[11px] font-medium text-slate-400 mb-1.5 block">
        {label}
        {hint && <span className="text-slate-600 ml-1">{hint}</span>}
      </label>
      {children}
    </div>
  );
}

function AlphaTradeConnectionCard() {
  const { connected, connectedEmail, connecting, connect, disconnect } = useAlphaTradeConnection();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);

  const handleConnect = async (e) => {
    e.preventDefault();
    setError(null);
    try {
      await connect(email, password);
      setPassword("");
    } catch (err) {
      setError(err.message || "Connexion à AlphaTrade impossible.");
    }
  };

  return (
    <div className="mt-6 rounded-2xl bg-[#0d1220] border border-[#1a2332] p-6 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          {connected ? <Link2 className="w-4 h-4 text-emerald-400" /> : <Link2 className="w-4 h-4 text-slate-500" />}
          Connexion AlphaTrade
        </h3>
        <p className="mt-1 text-xs text-slate-400 max-w-xl">
          Requise pour exporter des signaux depuis Export Signaux. Utilisez le même email et
          mot de passe que sur l'application AlphaTrade — ils ne transitent que le temps de
          cette connexion et ne sont jamais conservés ici, seul un jeton d'accès l'est.
        </p>
      </div>

      {connected ? (
        <div className="flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
          <div className="flex items-center gap-2 text-xs text-emerald-400">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
            Connecté en tant que {connectedEmail}
          </div>
          <button
            type="button"
            onClick={disconnect}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-slate-300 text-xs font-medium hover:border-[#2a3548] transition-colors"
          >
            <Unlink className="w-3.5 h-3.5" />
            Se déconnecter
          </button>
        </div>
      ) : (
        <form onSubmit={handleConnect} className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Email AlphaTrade">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="vous@exemple.com"
                className={inputCls}
                autoComplete="off"
                required
              />
            </Field>
            <Field label="Mot de passe AlphaTrade">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputCls}
                autoComplete="off"
                required
              />
            </Field>
          </div>
          {error && (
            <div className="flex items-start gap-2 px-3 py-2.5 rounded-lg border text-xs bg-red-500/5 border-red-500/20 text-red-400">
              <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}
          <button
            type="submit"
            disabled={connecting || !email || !password}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-[#0a0e17] font-semibold text-sm hover:from-amber-400 hover:to-amber-500 disabled:opacity-40 transition-all"
          >
            {connecting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Link2 className="w-4 h-4" />}
            {connecting ? "Connexion…" : "Se connecter à AlphaTrade"}
          </button>
        </form>
      )}
    </div>
  );
}

export default function Settings() {
  const { settings, updateSettings } = useAISettings();
  const providers = getAllProviders();

  const [providerId, setProviderId] = useState(settings.providerId);
  const [model, setModel] = useState(settings.model);
  const [apiKey, setApiKey] = useState(settings.apiKey || "");
  const [showKey, setShowKey] = useState(false);
  const [params, setParams] = useState({ ...AI_PARAM_DEFAULTS, ...(settings.params || {}) });

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null); // { ok, message }
  const [saved, setSaved] = useState(false);

  const provider = getProvider(providerId);

  const handleProviderChange = (id) => {
    const next = getProvider(id);
    setProviderId(id);
    setModel(next?.defaultModel || "");
    setApiKey("");
    setTestResult(null);
    setSaved(false);
  };

  const setParam = (key, value) => {
    setParams((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  };

  const handleTest = async () => {
    if (!provider) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await provider.testConnection({ apiKey, model });
      setTestResult(result);
    } catch (err) {
      setTestResult({ ok: false, message: err.message || "Échec de la connexion." });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = () => {
    updateSettings({ providerId, model, apiKey, params });
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  return (
    <div className="p-6 lg:p-10 max-w-3xl">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <SettingsIcon className="w-4 h-4 text-amber-400/70" />
          <span className="text-xs font-bold text-amber-400/70 tracking-widest uppercase">
            Administration
          </span>
        </div>
        <h2 className="text-3xl lg:text-4xl font-bold font-heading text-white tracking-tight">
          Paramètres IA
        </h2>
        <p className="mt-2 text-slate-400 text-base max-w-xl">
          Configurez le fournisseur d'intelligence artificielle utilisé par l'AI Strategy
          Designer. Votre clé API reste stockée uniquement dans ce navigateur et n'est
          jamais conservée sur nos serveurs — elle transite uniquement le temps de la requête.
        </p>
      </div>

      <div className="rounded-2xl bg-[#0d1220] border border-[#1a2332] p-6 space-y-6">
        {/* Provider selector */}
        <Field label="Fournisseur">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            {providers.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => handleProviderChange(p.id)}
                className={`text-left px-3 py-2.5 rounded-xl border transition-colors ${
                  p.id === providerId
                    ? "bg-amber-500/10 border-amber-500/30 text-amber-400"
                    : "bg-[#0a0e17] border-[#1a2332] text-slate-400 hover:border-[#2a3548]"
                }`}
              >
                <p className="text-sm font-semibold">{p.name}</p>
                <p className="text-[10px] text-slate-600 mt-0.5">{p.models.length} modèle(s)</p>
              </button>
            ))}
          </div>
        </Field>

        {/* Model selector */}
        {provider && (
          <Field label="Modèle">
            <select
              value={model}
              onChange={(e) => {
                setModel(e.target.value);
                setSaved(false);
              }}
              className={`${inputCls} cursor-pointer`}
            >
              {provider.models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                  {m.description ? ` — ${m.description}` : ""}
                </option>
              ))}
            </select>
          </Field>
        )}

        {/* API key */}
        {provider && (
          <Field label={provider.apiKeyLabel}>
            <div className="relative">
              <input
                type={showKey ? "text" : "password"}
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value);
                  setTestResult(null);
                  setSaved(false);
                }}
                placeholder={provider.apiKeyPlaceholder}
                className={`${inputCls} pr-10`}
                autoComplete="off"
              />
              <button
                type="button"
                onClick={() => setShowKey((v) => !v)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                tabIndex={-1}
              >
                {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            {provider.docsUrl && (
              <a
                href={provider.docsUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-amber-400/80 hover:text-amber-300"
              >
                Obtenir une clé <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </Field>
        )}

        {/* Advanced params */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2 border-t border-[#1a2332]">
          <Field label="Température" hint={`(${params.temperature})`}>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={params.temperature}
              onChange={(e) => setParam("temperature", Number(e.target.value))}
              className="w-full accent-amber-500"
            />
            <p className="text-[10px] text-slate-600 mt-1">Créativité des réponses</p>
          </Field>
          <Field label="Max tokens">
            <input
              type="number"
              min={16}
              max={8192}
              step={16}
              value={params.maxTokens}
              onChange={(e) => setParam("maxTokens", Number(e.target.value))}
              className={inputCls}
            />
          </Field>
          <Field label="Top P" hint={`(${params.topP})`}>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={params.topP}
              onChange={(e) => setParam("topP", Number(e.target.value))}
              className="w-full accent-amber-500"
            />
            <p className="text-[10px] text-slate-600 mt-1">Diversité du vocabulaire</p>
          </Field>
        </div>

        {/* Test result */}
        {testResult && (
          <div
            className={`flex items-start gap-2 px-3 py-2.5 rounded-lg border text-xs ${
              testResult.ok
                ? "bg-emerald-500/5 border-emerald-500/20 text-emerald-400"
                : "bg-red-500/5 border-red-500/20 text-red-400"
            }`}
          >
            {testResult.ok ? (
              <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" />
            ) : (
              <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            )}
            <span>{testResult.message}</span>
          </div>
        )}

        {/* Actions */}
        <div className="flex flex-wrap items-center gap-3 pt-2">
          <button
            type="button"
            onClick={handleTest}
            disabled={testing || !apiKey}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[#0a0e17] border border-[#1a2332] text-slate-300 text-sm font-medium hover:border-[#2a3548] disabled:opacity-40 transition-colors"
          >
            {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            {testing ? "Test en cours…" : "Tester la connexion"}
          </button>
          <button
            type="button"
            onClick={handleSave}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-[#0a0e17] font-semibold text-sm hover:from-amber-400 hover:to-amber-500 transition-all"
          >
            <Save className="w-4 h-4" />
            Enregistrer
          </button>
          {saved && <span className="text-xs text-emerald-400">Paramètres enregistrés.</span>}
        </div>
      </div>

      <AlphaTradeConnectionCard />
    </div>
  );
}
