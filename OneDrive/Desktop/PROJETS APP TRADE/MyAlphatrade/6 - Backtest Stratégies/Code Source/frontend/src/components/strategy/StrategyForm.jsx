import React, { useState } from "react";
import { X, Loader2, FileText, Globe, ArrowRightLeft, LogOut, Shield } from "lucide-react";
import GeneralInfo from "@/components/strategy/sections/GeneralInfo";
import MarketProfile from "@/components/strategy/sections/MarketProfile";
import EntryConditions from "@/components/strategy/sections/EntryConditions";
import ExitConditions from "@/components/strategy/sections/ExitConditions";
import RiskManagement from "@/components/strategy/sections/RiskManagement";

const EMPTY = {
  name: "",
  description: "",
  author: "",
  version: "1.0",
  parent_version_id: null,
  asset_scope: "specific",
  asset_symbols: [],
  asset_category: null,
  primary_timeframe: "M15",
  secondary_timeframes: [],
  market_profile: {
    sessions: [],
    volatility: "any",
    market_type: "any",
    ideal_conditions: "",
  },
  entry_conditions: { buy: [], sell: [] },
  exit_conditions: {
    take_profit: { type: "pips", value: 30, params: null },
    stop_loss: { type: "pips", value: 15, params: null },
    break_even: { enabled: false, trigger_pips: 0, offset_pips: 0 },
    trailing_stop: { enabled: false, type: "pips", distance: 10 },
    indicator_exit: { enabled: false, rule: "" },
    time_exit: { enabled: false, max_bars: 60 },
  },
  risk_management: {
    type: "percent",
    risk_value: 1,
    min_rr: 2,
    max_positions: 1,
    max_drawdown: 5,
  },
  status: "draft",
};

const TABS = [
  { id: "general", label: "Général", icon: FileText },
  { id: "profile", label: "Profil marché", icon: Globe },
  { id: "entries", label: "Entrées", icon: ArrowRightLeft },
  { id: "exits", label: "Sorties", icon: LogOut },
  { id: "risk", label: "Risque", icon: Shield },
];

export default function StrategyForm({ strategy, onSave, onClose }) {
  const [form, setForm] = useState(() => ({
    ...EMPTY,
    ...(strategy || {}),
    market_profile: { ...EMPTY.market_profile, ...(strategy?.market_profile || {}) },
    entry_conditions: { ...EMPTY.entry_conditions, ...(strategy?.entry_conditions || {}) },
    exit_conditions: { ...EMPTY.exit_conditions, ...(strategy?.exit_conditions || {}) },
    risk_management: { ...EMPTY.risk_management, ...(strategy?.risk_management || {}) },
  }));
  const [activeTab, setActiveTab] = useState("general");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const set = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name) {
      setError("Le nom de la stratégie est obligatoire.");
      setActiveTab("general");
      return;
    }
    setSaving(true);
    try {
      await onSave(form);
    } catch (err) {
      setError(err.message || "Erreur lors de l'enregistrement.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />

      <div className="relative bg-[#0d1220] border border-[#1a2332] rounded-2xl w-full max-w-4xl max-h-[92vh] flex flex-col shadow-2xl shadow-black/50">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#1a2332] flex-shrink-0">
          <h3 className="text-lg font-bold text-white">
            {strategy ? "Modifier la stratégie" : "Nouvelle stratégie"}
          </h3>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-500 hover:text-white hover:bg-white/5 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 px-4 py-2 border-b border-[#1a2332] overflow-x-auto flex-shrink-0">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${
                activeTab === tab.id
                  ? "bg-amber-500/10 text-amber-400"
                  : "text-slate-500 hover:text-white hover:bg-white/5"
              }`}
            >
              <tab.icon className="w-3.5 h-3.5" />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <form onSubmit={handleSubmit} className="flex flex-col flex-1 overflow-hidden">
          <div className="flex-1 overflow-y-auto p-6">
            {activeTab === "general" && <GeneralInfo form={form} set={set} />}
            {activeTab === "profile" && <MarketProfile form={form} set={set} />}
            {activeTab === "entries" && <EntryConditions form={form} set={set} />}
            {activeTab === "exits" && <ExitConditions form={form} set={set} />}
            {activeTab === "risk" && <RiskManagement form={form} set={set} />}
          </div>

          {error && (
            <p className="px-6 text-red-400 text-xs text-center">{error}</p>
          )}

          {/* Footer */}
          <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-[#1a2332] flex-shrink-0">
            <div className="flex items-center gap-2">
              <select
                value={form.status}
                onChange={(e) => set("status", e.target.value)}
                className="px-3 py-2 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-white text-xs focus:outline-none focus:border-amber-500/40"
              >
                <option value="draft">Brouillon</option>
                <option value="tested">Testée</option>
                <option value="active">Active</option>
                <option value="archived">Archivée</option>
              </select>
            </div>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2.5 rounded-xl text-sm font-medium text-slate-400 hover:text-white hover:bg-white/5 transition-colors"
              >
                Annuler
              </button>
              <button
                type="submit"
                disabled={saving}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-[#0a0e17] font-semibold text-sm hover:from-amber-400 hover:to-amber-500 disabled:opacity-50 transition-all"
              >
                {saving && <Loader2 className="w-4 h-4 animate-spin" />}
                {strategy ? "Enregistrer" : "Créer"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}