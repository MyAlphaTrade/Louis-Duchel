import React from "react";
import {
  TRADING_SESSIONS,
  VOLATILITY_LEVELS,
  MARKET_TYPES,
} from "@/lib/indicators";
import { Check } from "lucide-react";

const inputCls =
  "w-full px-3 py-2 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40 transition-colors";

function SectionTitle({ children }) {
  return (
    <h4 className="text-xs font-semibold text-amber-400/70 tracking-widest uppercase mb-4">
      {children}
    </h4>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="text-[11px] font-medium text-slate-400 mb-1.5 block">{label}</label>
      {children}
    </div>
  );
}

export default function MarketProfile({ form, set }) {
  const profile = form.market_profile || {};

  const update = (updates) =>
    set("market_profile", { ...profile, ...updates });

  const toggleSession = (sessionId) => {
    const current = profile.sessions || [];
    const next = current.includes(sessionId)
      ? current.filter((s) => s !== sessionId)
      : [...current, sessionId];
    update({ sessions: next });
  };

  return (
    <div className="space-y-6">
      <div>
        <SectionTitle>Profil de marché idéal</SectionTitle>
        <p className="text-xs text-slate-500 mb-4">
          Définissez les conditions optimales d'utilisation. L'IA et AlphaTrade pourront vérifier
          automatiquement si les conditions actuelles correspondent.
        </p>

        {/* Sessions */}
        <Field label="Sessions de trading">
          <div className="flex flex-wrap gap-2">
            {TRADING_SESSIONS.map((session) => {
              const selected = profile.sessions?.includes(session.id);
              return (
                <button
                  key={session.id}
                  type="button"
                  onClick={() => toggleSession(session.id)}
                  className={`px-3 py-2 rounded-lg text-xs font-medium border transition-all ${
                    selected
                      ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
                      : "bg-[#0a0e17] border-[#1a2332] text-slate-500 hover:text-white"
                  }`}
                >
                  {selected && <Check className="w-3 h-3 inline mr-1" />}
                  {session.label}
                </button>
              );
            })}
          </div>
        </Field>

        {/* Volatility + Market type */}
        <div className="grid sm:grid-cols-2 gap-4 mt-4">
          <Field label="Volatilité recommandée">
            <select
              className={inputCls}
              value={profile.volatility || "any"}
              onChange={(e) => update({ volatility: e.target.value })}
            >
              {VOLATILITY_LEVELS.map((v) => (
                <option key={v.id} value={v.id}>{v.label}</option>
              ))}
            </select>
          </Field>
          <Field label="Type de marché">
            <select
              className={inputCls}
              value={profile.market_type || "any"}
              onChange={(e) => update({ market_type: e.target.value })}
            >
              {MARKET_TYPES.map((m) => (
                <option key={m.id} value={m.id}>{m.label} — {m.description}</option>
              ))}
            </select>
          </Field>
        </div>

        {/* Ideal conditions */}
        <div className="mt-4">
          <Field label="Conditions idéales (description libre)">
            <textarea
              className={inputCls}
              rows={3}
              value={profile.ideal_conditions || ""}
              onChange={(e) => update({ ideal_conditions: e.target.value })}
              placeholder="Ex: Forte volatilité, annonces économiques, session de Londres active…"
            />
          </Field>
        </div>
      </div>
    </div>
  );
}