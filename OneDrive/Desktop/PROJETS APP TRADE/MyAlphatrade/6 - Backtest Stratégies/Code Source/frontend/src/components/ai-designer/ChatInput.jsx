import React, { useState, useRef, useEffect } from "react";
import { Send, Sparkles, Plus, Loader2 } from "lucide-react";

const inputCls =
  "flex-1 px-4 py-3 rounded-xl bg-[#0a0e17] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40 transition-colors resize-none";

/**
 * ChatInput — Zone de saisie avec boutons d'action.
 * - Envoyer : envoie le message à l'IA
 * - Générer la stratégie : déclenche la génération d'une stratégie structurée
 * - Nouvelle conversation : réinitialise la session
 */
export default function ChatInput({ onSend, onGenerate, onNewConversation, disabled, isGenerating }) {
  const [text, setText] = useState("");
  const textareaRef = useRef(null);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [text]);

  const handleSend = () => {
    if (!text.trim() || disabled) return;
    onSend(text.trim());
    setText("");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="p-4 border-t border-[#1a2332] bg-[#0d1220]">
      {/* Action buttons row */}
      <div className="flex items-center gap-2 mb-2">
        <button
          onClick={onNewConversation}
          className="flex items-center gap-1.5 text-[10px] font-medium px-3 py-1.5 rounded-lg bg-[#0a0e17] border border-[#1a2332] text-slate-400 hover:text-white hover:border-[#2a3548] transition-colors"
        >
          <Plus className="w-3 h-3" />
          Nouvelle conversation
        </button>
        <button
          onClick={onGenerate}
          disabled={isGenerating || disabled}
          className="flex items-center gap-1.5 text-[10px] font-bold px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 hover:bg-amber-500/20 disabled:opacity-40 transition-colors"
        >
          {isGenerating ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
          {isGenerating ? "Génération…" : "Générer la stratégie"}
        </button>
      </div>

      {/* Input row */}
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Décrivez votre idée de stratégie en langage naturel…"
          rows={1}
          className={inputCls}
          disabled={disabled}
        />
        <button
          onClick={handleSend}
          disabled={!text.trim() || disabled}
          className="flex-shrink-0 flex items-center justify-center w-11 h-11 rounded-xl bg-gradient-to-br from-amber-500 to-amber-600 text-[#0a0e17] hover:from-amber-400 hover:to-amber-500 disabled:opacity-40 transition-all"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}