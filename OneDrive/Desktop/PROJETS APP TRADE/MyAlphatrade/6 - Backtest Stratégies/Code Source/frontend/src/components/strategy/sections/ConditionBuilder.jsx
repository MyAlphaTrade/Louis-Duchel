import React from "react";
import {
  INDICATORS,
  INDICATOR_CATEGORIES,
  OPERATORS,
  getIndicator,
  getOperator,
  getIndicatorsByCategory,
} from "@/lib/indicators";
import { Trash2 } from "lucide-react";

const inputCls =
  "w-full px-3 py-2 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40 transition-colors";

const labelCls = "text-[10px] font-medium text-slate-500 mb-1 block";

function ParamField({ param, value, onChange }) {
  if (param.type === "number") {
    return (
      <div>
        <span className={labelCls}>{param.label}</span>
        <input
          type="number"
          step={param.step || 1}
          min={param.min}
          max={param.max}
          className={inputCls}
          value={value ?? param.default}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    );
  }
  if (param.type === "select") {
    const options =
      typeof param.options[0] === "string"
        ? param.options.map((o) => ({ value: o, label: o }))
        : param.options;
    return (
      <div>
        <span className={labelCls}>{param.label}</span>
        <select
          className={inputCls}
          value={value ?? param.default}
          onChange={(e) => onChange(e.target.value)}
        >
          {options.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>
    );
  }
  return null;
}

export default function ConditionBuilder({ condition, onChange, onDelete }) {
  const indicator = getIndicator(condition.indicator) || INDICATORS[0];
  const operator = getOperator(condition.operator) || OPERATORS[0];
  const targetIndicator = getIndicator(condition.target_indicator);
  const needsIndicatorTarget = operator.requires_target === "indicator";
  const needsValueTarget = operator.requires_target === "value";

  const handleIndicatorChange = (indicatorId) => {
    const ind = getIndicator(indicatorId);
    const defaultParams = {};
    ind.params.forEach((p) => { defaultParams[p.key] = p.default; });
    onChange({ ...condition, indicator: indicatorId, params: defaultParams });
  };

  const handleParamChange = (key, value) => {
    onChange({ ...condition, params: { ...condition.params, [key]: Number(value) } });
  };

  const handleOperatorChange = (operatorId) => {
    const op = getOperator(operatorId);
    const updates = { operator: operatorId };
    if (op.requires_target !== "indicator") {
      updates.target_indicator = null;
      updates.target_params = null;
    }
    if (op.requires_target !== "value") {
      updates.target_value = null;
    }
    onChange({ ...condition, ...updates });
  };

  const handleTargetIndicatorChange = (indicatorId) => {
    const ind = getIndicator(indicatorId);
    const defaultParams = {};
    ind.params.forEach((p) => { defaultParams[p.key] = p.default; });
    onChange({ ...condition, target_indicator: indicatorId, target_params: defaultParams });
  };

  const handleTargetParamChange = (key, value) => {
    onChange({
      ...condition,
      target_params: { ...condition.target_params, [key]: Number(value) },
    });
  };

  return (
    <div className="p-4 rounded-xl bg-[#0a0e17] border border-[#1a2332]">
      {/* Row 1: Indicator + Operator */}
      <div className="grid sm:grid-cols-2 gap-3 mb-3">
        <div>
          <span className={labelCls}>Indicateur</span>
          <select
            className={inputCls}
            value={condition.indicator}
            onChange={(e) => handleIndicatorChange(e.target.value)}
          >
            {INDICATOR_CATEGORIES.map((cat) => (
              <optgroup key={cat} label={cat}>
                {getIndicatorsByCategory(cat).map((ind) => (
                  <option key={ind.id} value={ind.id}>{ind.name}</option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
        <div>
          <span className={labelCls}>Opérateur</span>
          <select
            className={inputCls}
            value={condition.operator}
            onChange={(e) => handleOperatorChange(e.target.value)}
          >
            {OPERATORS.map((op) => (
              <option key={op.id} value={op.id}>{op.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Row 2: Indicator params */}
      {indicator.params.length > 0 && (
        <div className="grid sm:grid-cols-3 gap-3 mb-3">
          {indicator.params.map((param) => (
            <ParamField
              key={param.key}
              param={param}
              value={condition.params?.[param.key]}
              onChange={(val) => handleParamChange(param.key, val)}
            />
          ))}
        </div>
      )}

      {/* Row 3: Target indicator + params */}
      {needsIndicatorTarget && (
        <div className="pt-3 border-t border-[#1a2332]">
          <span className={`${labelCls} text-amber-400/60`}>Cible (indicateur comparé)</span>
          <div className="grid sm:grid-cols-2 gap-3 mb-3">
            <select
              className={inputCls}
              value={condition.target_indicator || ""}
              onChange={(e) => handleTargetIndicatorChange(e.target.value)}
            >
              <option value="">Sélectionner…</option>
              {INDICATORS.map((ind) => (
                <option key={ind.id} value={ind.id}>{ind.name}</option>
              ))}
            </select>
          </div>
          {targetIndicator && targetIndicator.params.length > 0 && (
            <div className="grid sm:grid-cols-3 gap-3">
              {targetIndicator.params.map((param) => (
                <ParamField
                  key={param.key}
                  param={param}
                  value={condition.target_params?.[param.key]}
                  onChange={(val) => handleTargetParamChange(param.key, val)}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Row 3 alt: Target value */}
      {needsValueTarget && (
        <div className="pt-3 border-t border-[#1a2332]">
          <div className="grid sm:grid-cols-3 gap-3">
            <div>
              <span className={labelCls}>Valeur cible</span>
              <input
                type="number"
                step="0.01"
                className={inputCls}
                value={condition.target_value ?? ""}
                onChange={(e) =>
                  onChange({ ...condition, target_value: Number(e.target.value) })
                }
                placeholder="50"
              />
            </div>
          </div>
        </div>
      )}

      {/* Delete */}
      <div className="flex justify-end mt-2">
        <button
          type="button"
          onClick={onDelete}
          className="p-1.5 rounded-lg text-slate-600 hover:text-rose-400 hover:bg-rose-500/5 transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}