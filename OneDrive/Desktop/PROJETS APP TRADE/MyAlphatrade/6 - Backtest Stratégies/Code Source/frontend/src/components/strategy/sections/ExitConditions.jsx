import React from "react";
import { Target, Shield, Anchor, Move, Activity, Clock } from "lucide-react";

const inputCls =
  "w-full px-3 py-2 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40 transition-colors";

const labelCls = "text-[11px] font-medium text-slate-400 mb-1.5 block";

const EXIT_TYPES = [
  { value: "pips", label: "Pips" },
  { value: "percent", label: "Pourcentage" },
  { value: "atr", label: "ATR (multiplicateur)" },
];

function ToggleCard({ icon: Icon, title, description, enabled, onToggle, children }) {
  return (
    <div className={`p-4 rounded-xl border transition-all ${
      enabled ? "border-amber-500/20 bg-amber-500/[0.02]" : "border-[#1a2332] bg-[#0a0e17]"
    }`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon className={`w-4 h-4 ${enabled ? "text-amber-400" : "text-slate-600"}`} />
          <span className="text-sm font-semibold text-white">{title}</span>
        </div>
        <button
          type="button"
          onClick={onToggle}
          className={`relative w-9 h-5 rounded-full transition-colors ${
            enabled ? "bg-amber-500" : "bg-slate-700"
          }`}
        >
          <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
            enabled ? "translate-x-4" : "translate-x-0.5"
          }`} />
        </button>
      </div>
      {enabled && children}
      {!enabled && <p className="text-xs text-slate-600">{description}</p>}
    </div>
  );
}

export default function ExitConditions({ form, set }) {
  const exits = form.exit_conditions || {};

  const update = (updates) =>
    set("exit_conditions", { ...exits, ...updates });

  return (
    <div className="space-y-4">
      {/* Take Profit + Stop Loss */}
      <div className="grid sm:grid-cols-2 gap-4">
        {/* TP */}
        <div className="p-4 rounded-xl bg-[#0a0e17] border border-[#1a2332]">
          <div className="flex items-center gap-2 mb-3">
            <Target className="w-4 h-4 text-emerald-400" />
            <span className="text-sm font-semibold text-white">Take Profit</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <span className={labelCls}>Type</span>
              <select
                className={inputCls}
                value={exits.take_profit?.type || "pips"}
                onChange={(e) =>
                  update({ take_profit: { ...exits.take_profit, type: e.target.value } })
                }
              >
                {EXIT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <span className={labelCls}>
                {exits.take_profit?.type === "atr" ? "Multiplicateur" : "Valeur"}
              </span>
              <input
                type="number"
                step="0.1"
                className={inputCls}
                value={exits.take_profit?.value ?? ""}
                onChange={(e) =>
                  update({ take_profit: { ...exits.take_profit, value: Number(e.target.value) } })
                }
                placeholder="30"
              />
            </div>
          </div>
        </div>

        {/* SL */}
        <div className="p-4 rounded-xl bg-[#0a0e17] border border-[#1a2332]">
          <div className="flex items-center gap-2 mb-3">
            <Shield className="w-4 h-4 text-rose-400" />
            <span className="text-sm font-semibold text-white">Stop Loss</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <span className={labelCls}>Type</span>
              <select
                className={inputCls}
                value={exits.stop_loss?.type || "pips"}
                onChange={(e) =>
                  update({ stop_loss: { ...exits.stop_loss, type: e.target.value } })
                }
              >
                {EXIT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <span className={labelCls}>
                {exits.stop_loss?.type === "atr" ? "Multiplicateur" : "Valeur"}
              </span>
              <input
                type="number"
                step="0.1"
                className={inputCls}
                value={exits.stop_loss?.value ?? ""}
                onChange={(e) =>
                  update({ stop_loss: { ...exits.stop_loss, value: Number(e.target.value) } })
                }
                placeholder="15"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Break Even */}
      <ToggleCard
        icon={Anchor}
        title="Break Even"
        description="Déplacer le SL au point d'entrée après un certain profit"
        enabled={exits.break_even?.enabled}
        onToggle={() =>
          update({ break_even: { ...exits.break_even, enabled: !exits.break_even?.enabled } })
        }
      >
        <div className="grid grid-cols-2 gap-3">
          <div>
            <span className={labelCls}>Trigger (pips)</span>
            <input
              type="number"
              step="0.5"
              className={inputCls}
              value={exits.break_even?.trigger_pips ?? ""}
              onChange={(e) =>
                update({ break_even: { ...exits.break_even, trigger_pips: Number(e.target.value) } })
              }
              placeholder="15"
            />
          </div>
          <div>
            <span className={labelCls}>Offset (pips)</span>
            <input
              type="number"
              step="0.5"
              className={inputCls}
              value={exits.break_even?.offset_pips ?? ""}
              onChange={(e) =>
                update({ break_even: { ...exits.break_even, offset_pips: Number(e.target.value) } })
              }
              placeholder="0"
            />
          </div>
        </div>
      </ToggleCard>

      {/* Trailing Stop */}
      <ToggleCard
        icon={Move}
        title="Trailing Stop"
        description="Suivre le prix avec un stop dynamique"
        enabled={exits.trailing_stop?.enabled}
        onToggle={() =>
          update({ trailing_stop: { ...exits.trailing_stop, enabled: !exits.trailing_stop?.enabled } })
        }
      >
        <div className="grid grid-cols-2 gap-3">
          <div>
            <span className={labelCls}>Type</span>
            <select
              className={inputCls}
              value={exits.trailing_stop?.type || "pips"}
              onChange={(e) =>
                update({ trailing_stop: { ...exits.trailing_stop, type: e.target.value } })
              }
            >
              <option value="pips">Pips</option>
              <option value="atr">ATR</option>
              <option value="percent">Pourcentage</option>
            </select>
          </div>
          <div>
            <span className={labelCls}>Distance</span>
            <input
              type="number"
              step="0.5"
              className={inputCls}
              value={exits.trailing_stop?.distance ?? ""}
              onChange={(e) =>
                update({ trailing_stop: { ...exits.trailing_stop, distance: Number(e.target.value) } })
              }
              placeholder="10"
            />
          </div>
        </div>
      </ToggleCard>

      {/* Indicator Exit */}
      <ToggleCard
        icon={Activity}
        title="Sortie par indicateur"
        description="Sortir basé sur une règle d'indicateur"
        enabled={exits.indicator_exit?.enabled}
        onToggle={() =>
          update({ indicator_exit: { ...exits.indicator_exit, enabled: !exits.indicator_exit?.enabled } })
        }
      >
        <div>
          <span className={labelCls}>Règle de sortie</span>
          <input
            className={inputCls}
            value={exits.indicator_exit?.rule || ""}
            onChange={(e) =>
              update({ indicator_exit: { ...exits.indicator_exit, rule: e.target.value } })
            }
            placeholder="Ex: RSI retourne à 50"
          />
        </div>
      </ToggleCard>

      {/* Time Exit */}
      <ToggleCard
        icon={Clock}
        title="Sortie temporelle"
        description="Fermer la position après un nombre de bars"
        enabled={exits.time_exit?.enabled}
        onToggle={() =>
          update({ time_exit: { ...exits.time_exit, enabled: !exits.time_exit?.enabled } })
        }
      >
        <div>
          <span className={labelCls}>Bars maximum</span>
          <input
            type="number"
            step="1"
            className={inputCls}
            value={exits.time_exit?.max_bars ?? ""}
            onChange={(e) =>
              update({ time_exit: { ...exits.time_exit, max_bars: Number(e.target.value) } })
            }
            placeholder="60"
          />
        </div>
      </ToggleCard>
    </div>
  );
}