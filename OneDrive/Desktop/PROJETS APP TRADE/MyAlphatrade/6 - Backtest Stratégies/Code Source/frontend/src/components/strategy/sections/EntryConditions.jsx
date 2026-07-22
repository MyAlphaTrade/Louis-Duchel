import React from "react";
import ConditionBuilder from "@/components/strategy/sections/ConditionBuilder";
import { TrendingUp, TrendingDown, Plus, Power } from "lucide-react";

const genId = () => `cond_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;

function ConditionRow({ condition, onChange, onDelete, accent }) {
  const enabled = condition.enabled !== false;
  return (
    <div className={`relative rounded-xl border transition-all ${
      enabled ? "border-[#1a2332]" : "border-[#1a2332] opacity-50"
    }`}>
      <div className="flex items-center gap-2 px-4 py-2 border-b border-[#1a2332]">
        <button
          type="button"
          onClick={() => onChange({ ...condition, enabled: !enabled })}
          className={`flex items-center gap-1.5 text-[10px] font-medium px-2 py-1 rounded-full transition-colors ${
            enabled
              ? accent === "buy"
                ? "bg-emerald-500/10 text-emerald-400"
                : "bg-rose-500/10 text-rose-400"
              : "bg-slate-500/10 text-slate-500"
          }`}
        >
          <Power className="w-3 h-3" />
          {enabled ? "Activée" : "Désactivée"}
        </button>
      </div>
      <div className="p-3">
        <ConditionBuilder
          condition={condition}
          onChange={onChange}
          onDelete={onDelete}
        />
      </div>
    </div>
  );
}

function ConditionGroup({ title, icon: Icon, accent, conditions, onUpdate, onAdd }) {
  const accentCls = accent === "buy" ? "text-emerald-400" : "text-rose-400";
  const addBtnCls = accent === "buy"
    ? "border-emerald-500/20 text-emerald-400 hover:bg-emerald-500/5"
    : "border-rose-500/20 text-rose-400 hover:bg-rose-500/5";

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon className={`w-4 h-4 ${accentCls}`} />
          <h4 className={`text-sm font-bold ${accentCls}`}>{title}</h4>
          <span className="text-[10px] text-slate-600 px-2 py-0.5 rounded-full bg-white/5">
            {conditions.length} condition{conditions.length !== 1 ? "s" : ""}
          </span>
        </div>
        <button
          type="button"
          onClick={onAdd}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border ${addBtnCls} transition-colors`}
        >
          <Plus className="w-3.5 h-3.5" />
          Ajouter
        </button>
      </div>

      {conditions.length === 0 ? (
        <div className="text-center py-6 rounded-xl bg-[#0a0e17] border border-dashed border-[#1a2332]">
          <p className="text-xs text-slate-600">Aucune condition. Cliquez sur « Ajouter ».</p>
        </div>
      ) : (
        <div className="space-y-3">
          {conditions.map((cond, idx) => (
            <ConditionRow
              key={cond.id || idx}
              condition={cond}
              accent={accent}
              onChange={(updated) => {
                const next = [...conditions];
                next[idx] = updated;
                onUpdate(next);
              }}
              onDelete={() => {
                const next = conditions.filter((_, i) => i !== idx);
                onUpdate(next);
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function EntryConditions({ form, set }) {
  const entries = form.entry_conditions || { buy: [], sell: [] };

  const updateEntries = (updates) =>
    set("entry_conditions", { ...entries, ...updates });

  const addBuy = () => {
    const newCond = {
      id: genId(),
      enabled: true,
      indicator: "ema",
      params: { period: 9 },
      operator: "crosses_above",
      target_indicator: "ema",
      target_params: { period: 21 },
      target_value: null,
    };
    updateEntries({ buy: [...(entries.buy || []), newCond] });
  };

  const addSell = () => {
    const newCond = {
      id: genId(),
      enabled: true,
      indicator: "ema",
      params: { period: 9 },
      operator: "crosses_below",
      target_indicator: "ema",
      target_params: { period: 21 },
      target_value: null,
    };
    updateEntries({ sell: [...(entries.sell || []), newCond] });
  };

  return (
    <div className="space-y-8">
      <ConditionGroup
        title="Conditions BUY"
        icon={TrendingUp}
        accent="buy"
        conditions={entries.buy || []}
        onUpdate={(buy) => updateEntries({ buy })}
        onAdd={addBuy}
      />

      <div className="border-t border-[#1a2332]" />

      <ConditionGroup
        title="Conditions SELL"
        icon={TrendingDown}
        accent="sell"
        conditions={entries.sell || []}
        onUpdate={(sell) => updateEntries({ sell })}
        onAdd={addSell}
      />
    </div>
  );
}