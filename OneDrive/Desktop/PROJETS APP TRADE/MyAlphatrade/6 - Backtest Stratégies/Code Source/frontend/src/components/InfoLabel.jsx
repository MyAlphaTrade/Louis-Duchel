import React from "react";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import { Info } from "lucide-react";

/**
 * Reusable label with an info tooltip.
 * Use anywhere a parameter needs a brief explanation.
 */
export default function InfoLabel({ label, tooltip, children, className = "" }) {
  return (
    <div className={`flex items-center gap-1 mb-1.5 ${className}`}>
      <label className="text-[11px] font-medium text-slate-400">{label}</label>
      {tooltip && (
        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="inline-flex">
                <Info className="w-3 h-3 text-slate-600 hover:text-amber-400 cursor-help transition-colors" />
              </span>
            </TooltipTrigger>
            <TooltipContent
              side="top"
              className="max-w-[240px] text-center leading-relaxed bg-[#1a2332] border border-[#2a3548] text-slate-300"
            >
              {tooltip}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      )}
      {children}
    </div>
  );
}