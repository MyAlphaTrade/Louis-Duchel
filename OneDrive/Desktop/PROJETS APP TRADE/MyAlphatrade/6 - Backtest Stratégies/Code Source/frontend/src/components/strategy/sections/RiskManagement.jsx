import React from "react";
import { Shield, Percent, DollarSign, Coins, Layers, TrendingDown } from "lucide-react";

const inputCls =
  "w-full px-3 py-2 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40 transition-colors";

const labelCls = "text-[11px] font-medium text-slate-400 mb-1.5 block";

const RISK_TYPES = [
  { value: "percent", label: "Pourcentage du capital", icon: Percent },
  { value: "fixed", label: "Risque fixe ($)", icon: DollarSign },
  { value: "lots", label: "Lots fixes", icon: Coins },
];

function SectionTitle({ children }) {
  return (
    <h4 className="text-xs font-semibold text-amber-400/70 tracking-widest uppercase mb-4">
      {children}
    </h4>
  );
}

export default function RiskManagement({ form, set }) {
  const risk = form.risk_management || {};

  const update = (updates) =>
    set("risk_management", { ...risk, ...updates });

  return (
    <div className="space-y-6">
      <div>
        <SectionTitle>Mode de sizing</SectionTitle>
        <div className="grid sm:grid-cols-3 gap-3 mb-4">
          {RISK_TYPES.map((type) => {
            const selected = (risk.type || "percent") === type.value;
            return (
              <button
                key={type.value}
                type="button"
                onClick={() => update({ type: type.value })}
                className={`flex flex-col items-center gap-2 p-4 rounded-xl border transition-all ${
                  selected
                    ? "bg-amber-500/10 border-amber-500/20 text-amber-400"
                    : "bg-[#0a0e17] border-[#1a2332] text-slate-500 hover:text-white"
                }`}
              >
                <type.icon className="w-5 h-5" />
                <span className="text-xs font-medium text-center">{type.label}</span>
              </button>
            );
          })}
        </div>

        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className={labelCls}>
              {risk.type === "percent" ? "Risque par trade (%)" : risk.type === "fixed" ? "Risque par trade ($)" : "Lots par trade"}
            </label>
            <input
              type="number"
              step="0.01"
              className={inputCls}
              value={risk.risk_value ?? ""}
              onChange={(e) => update({ risk_value: Number(e.target.value) })}
              placeholder={risk.type === "percent" ? "1" : risk.type === "fixed" ? "100" : "0.01"}
            />
          </div>
          <div>
            <label className={labelCls}>Ratio Risque/Rendement minimum</label>
            <input
              type="number"
              step="0.1"
              className={inputCls}
              value={risk.min_rr ?? ""}
              onChange={(e) => update({ min_rr: Number(e.target.value) })}
              placeholder="2"
            />
          </div>
        </div>
      </div>

      <div className="border-t border-[#1a2332] pt-6">
        <SectionTitle>Limites de risque</SectionTitle>
        <div className="grid sm:grid-cols-2 gap-4">
          <div className="p-4 rounded-xl bg-[#0a0e17] border border-[#1a2332]">
            <div className="flex items-center gap-2 mb-2">
              <Layers className="w-4 h-4 text-blue-400" />
              <span className="text-sm font-semibold text-white">Positions maximum</span>
            </div>
            <input
              type="number"
              step="1"
              min="1"
              className={inputCls}
              value={risk.max_positions ?? ""}
              onChange={(e) => update({ max_positions: Number(e.target.value) })}
              placeholder="1"
            />
            <p className="text-[10px] text-slate-600 mt-1.5">Nombre maximum de positions simultanées</p>
          </div>

          <div className="p-4 rounded-xl bg-[#0a0e17] border border-[#1a2332]">
            <div className="flex items-center gap-2 mb-2">
              <TrendingDown className="w-4 h-4 text-rose-400" />
              <span className="text-sm font-semibold text-white">Drawdown maximum (%)</span>
            </div>
            <input
              type="number"
              step="0.5"
              min="0"
              className={inputCls}
              value={risk.max_drawdown ?? ""}
              onChange={(e) => update({ max_drawdown: Number(e.target.value) })}
              placeholder="5"
            />
            <p className="text-[10px] text-slate-600 mt-1.5">Pause automatique si le drawdown atteint ce seuil</p>
          </div>
        </div>
      </div>
    </div>
  );
}