import React, { useState } from "react";
import {
  ASSET_CATEGORIES,
  TIMEFRAMES,
  ASSET_COLORS,
  ASSET_ICONS,
  getAssetStyle,
} from "@/lib/assets";
import { X, Loader2 } from "lucide-react";

const EMPTY = {
  name: "",
  symbol: "",
  category: "Métaux",
  description: "",
  broker: "",
  market: "",
  color: "amber",
  icon: "TrendingUp",
  status: "active",
  digits: 2,
  pip_size: 0.01,
  min_lot: 0.01,
  max_lot: 100,
  lot_step: 0.01,
  default_timeframe: "M15",
  avg_spread: "",
  timezone: "UTC",
  trading_hours: "",
  data_source: "",
  tradingview_id: "",
  metatrader_id: "",
  deriv_id: "",
  order: 0,
};

function Field({ label, children, optional }) {
  return (
    <div>
      <label className="text-[11px] font-medium text-slate-400 mb-1.5 block">
        {label}
        {optional && <span className="text-slate-600 ml-1">(optionnel)</span>}
      </label>
      {children}
    </div>
  );
}

const inputCls =
  "w-full px-3 py-2 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40 transition-colors";

export default function AssetForm({ asset, onSave, onClose }) {
  const [form, setForm] = useState({ ...EMPTY, ...(asset || {}) });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const set = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (!form.name || !form.symbol || !form.category) {
      setError("Nom, symbole et catégorie sont obligatoires.");
      return;
    }
    setSaving(true);
    try {
      const data = {
        ...form,
        digits: Number(form.digits),
        pip_size: Number(form.pip_size),
        min_lot: Number(form.min_lot),
        max_lot: Number(form.max_lot),
        lot_step: Number(form.lot_step),
        avg_spread: form.avg_spread ? Number(form.avg_spread) : null,
        order: Number(form.order),
      };
      await onSave(data);
    } catch (err) {
      setError(err.message || "Erreur lors de l'enregistrement.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />

      <div className="relative bg-[#0d1220] border border-[#1a2332] rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl shadow-black/50">
        {/* Header */}
        <div className="sticky top-0 bg-[#0d1220] border-b border-[#1a2332] px-6 py-4 flex items-center justify-between z-10">
          <h3 className="text-lg font-bold text-white">
            {asset ? "Modifier l'actif" : "Nouvel actif"}
          </h3>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-500 hover:text-white hover:bg-white/5 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-6">
          {/* Section: Informations générales */}
          <div>
            <h4 className="text-xs font-semibold text-amber-400/70 tracking-widest uppercase mb-4">
              Informations générales
            </h4>
            <div className="grid sm:grid-cols-2 gap-4">
              <Field label="Nom complet">
                <input className={inputCls} value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Gold Spot" required />
              </Field>
              <Field label="Symbole">
                <input className={inputCls} value={form.symbol} onChange={(e) => set("symbol", e.target.value.toUpperCase())} placeholder="XAUUSD" required />
              </Field>
              <Field label="Catégorie">
                <select className={inputCls} value={form.category} onChange={(e) => set("category", e.target.value)}>
                  {ASSET_CATEGORIES.map((cat) => (
                    <option key={cat} value={cat}>{cat}</option>
                  ))}
                </select>
              </Field>
              <Field label="Broker">
                <input className={inputCls} value={form.broker} onChange={(e) => set("broker", e.target.value)} placeholder="Deriv, IC Markets…" />
              </Field>
              <Field label="Marché">
                <input className={inputCls} value={form.market} onChange={(e) => set("market", e.target.value)} placeholder="Forex, Synthétique…" />
              </Field>
              <Field label="Statut">
                <select className={inputCls} value={form.status} onChange={(e) => set("status", e.target.value)}>
                  <option value="active">Actif</option>
                  <option value="inactive">Inactif</option>
                </select>
              </Field>
              <div className="sm:col-span-2">
                <Field label="Description">
                  <textarea className={inputCls} rows={2} value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="Description de l'actif…" />
                </Field>
              </div>
            </div>

            {/* Color picker */}
            <div className="mt-4">
              <label className="text-[11px] font-medium text-slate-400 mb-1.5 block">Couleur</label>
              <div className="flex flex-wrap gap-2">
                {ASSET_COLORS.map((color) => {
                  const s = getAssetStyle(color);
                  return (
                    <button
                      key={color}
                      type="button"
                      onClick={() => set("color", color)}
                      className={`w-8 h-8 rounded-lg ${s.dot} ${form.color === color ? "ring-2 ring-white ring-offset-2 ring-offset-[#0d1220]" : ""} transition-all`}
                    />
                  );
                })}
              </div>
            </div>

            {/* Icon picker */}
            <div className="mt-4">
              <label className="text-[11px] font-medium text-slate-400 mb-1.5 block">Icône</label>
              <div className="flex flex-wrap gap-2">
                {Object.keys(ASSET_ICONS).map((iconName) => {
                  const Icon = ASSET_ICONS[iconName];
                  return (
                    <button
                      key={iconName}
                      type="button"
                      onClick={() => set("icon", iconName)}
                      className={`w-9 h-9 rounded-lg flex items-center justify-center border transition-all ${
                        form.icon === iconName
                          ? "bg-amber-500/10 border-amber-500/40 text-amber-400"
                          : "bg-[#0a0e17] border-[#1a2332] text-slate-500 hover:text-white"
                      }`}
                    >
                      <Icon className="w-4 h-4" />
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Section: Paramètres de trading */}
          <div>
            <h4 className="text-xs font-semibold text-amber-400/70 tracking-widest uppercase mb-4">
              Paramètres de trading
            </h4>
            <div className="grid sm:grid-cols-3 gap-4">
              <Field label="Décimales (Digits)">
                <input type="number" step="1" className={inputCls} value={form.digits} onChange={(e) => set("digits", e.target.value)} />
              </Field>
              <Field label="Taille du pip">
                <input type="number" step="0.0001" className={inputCls} value={form.pip_size} onChange={(e) => set("pip_size", e.target.value)} />
              </Field>
              <Field label="Timeframe par défaut">
                <select className={inputCls} value={form.default_timeframe} onChange={(e) => set("default_timeframe", e.target.value)}>
                  {TIMEFRAMES.map((tf) => (
                    <option key={tf} value={tf}>{tf}</option>
                  ))}
                </select>
              </Field>
              <Field label="Lot min">
                <input type="number" step="0.01" className={inputCls} value={form.min_lot} onChange={(e) => set("min_lot", e.target.value)} />
              </Field>
              <Field label="Lot max">
                <input type="number" step="0.01" className={inputCls} value={form.max_lot} onChange={(e) => set("max_lot", e.target.value)} />
              </Field>
              <Field label="Pas de lot">
                <input type="number" step="0.01" className={inputCls} value={form.lot_step} onChange={(e) => set("lot_step", e.target.value)} />
              </Field>
              <Field label="Spread moyen" optional>
                <input type="number" step="0.01" className={inputCls} value={form.avg_spread} onChange={(e) => set("avg_spread", e.target.value)} placeholder="—" />
              </Field>
              <Field label="Ordre d'affichage">
                <input type="number" step="1" className={inputCls} value={form.order} onChange={(e) => set("order", e.target.value)} />
              </Field>
            </div>
          </div>

          {/* Section: Paramètres techniques */}
          <div>
            <h4 className="text-xs font-semibold text-amber-400/70 tracking-widest uppercase mb-4">
              Paramètres techniques
            </h4>
            <div className="grid sm:grid-cols-2 gap-4">
              <Field label="Fuseau horaire">
                <input className={inputCls} value={form.timezone} onChange={(e) => set("timezone", e.target.value)} placeholder="UTC+0" />
              </Field>
              <Field label="Horaires de trading">
                <input className={inputCls} value={form.trading_hours} onChange={(e) => set("trading_hours", e.target.value)} placeholder="24/5" />
              </Field>
              <Field label="Source des données">
                <input className={inputCls} value={form.data_source} onChange={(e) => set("data_source", e.target.value)} placeholder="MT5, Deriv…" />
              </Field>
              <Field label="Identifiant TradingView" optional>
                <input className={inputCls} value={form.tradingview_id} onChange={(e) => set("tradingview_id", e.target.value)} placeholder="OANDA:XAUUSD" />
              </Field>
              <Field label="Identifiant MetaTrader" optional>
                <input className={inputCls} value={form.metatrader_id} onChange={(e) => set("metatrader_id", e.target.value)} placeholder="XAUUSD" />
              </Field>
              <Field label="Identifiant Deriv" optional>
                <input className={inputCls} value={form.deriv_id} onChange={(e) => set("deriv_id", e.target.value)} placeholder="frXAUUSD…" />
              </Field>
            </div>
          </div>

          {error && (
            <p className="text-red-400 text-xs text-center">{error}</p>
          )}

          {/* Footer */}
          <div className="flex items-center justify-end gap-3 pt-2 border-t border-[#1a2332]">
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
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
              {asset ? "Enregistrer" : "Créer"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}