import React from "react";
import ReactMarkdown from "react-markdown";
import { Bot, User, Loader2, Sparkles } from "lucide-react";

/**
 * ChatMessage — Affiche un message dans la conversation IA.
 * Supporte le markdown pour les réponses de l'assistant.
 */
export default function ChatMessage({ message }) {
  const isUser = message.role === "user";
  const isThinking = message.role === "assistant" && message.thinking;

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Avatar */}
      <div className={`flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${
        isUser ? "bg-blue-500/10" : "bg-gradient-to-br from-amber-400/20 to-amber-600/20"
      }`}>
        {isUser ? (
          <User className="w-4 h-4 text-blue-400" />
        ) : (
          <Bot className="w-4 h-4 text-amber-400" />
        )}
      </div>

      {/* Bubble */}
      <div className={`max-w-[75%] ${isUser ? "items-end" : "items-start"}`}>
        {isThinking ? (
          <div className="flex items-center gap-2 px-4 py-3 rounded-2xl bg-[#0d1220] border border-[#1a2332]">
            <Loader2 className="w-3.5 h-3.5 animate-spin text-amber-400" />
            <span className="text-xs text-slate-500">L'IA réfléchit…</span>
          </div>
        ) : (
          <div className={`px-4 py-3 rounded-2xl ${
            isUser
              ? "bg-blue-500/10 border border-blue-500/20 text-slate-200"
              : "bg-[#0d1220] border border-[#1a2332] text-slate-300"
          }`}>
            {message.announcement && (
              <div className="flex items-center gap-1.5 mb-2 text-[10px] text-amber-400/70 uppercase tracking-wider">
                <Sparkles className="w-3 h-3" />
                {message.announcement}
              </div>
            )}
            {isUser ? (
              <p className="text-sm whitespace-pre-wrap leading-relaxed">{message.content}</p>
            ) : (
              <ReactMarkdown className="text-sm prose prose-sm prose-invert max-w-none prose-p:my-1 prose-li:my-0 prose-headings:text-white prose-code:text-amber-300">
                {message.content}
              </ReactMarkdown>
            )}
          </div>
        )}
        {message.timestamp && (
          <span className="text-[9px] text-slate-700 mt-1 block px-1">
            {new Date(message.timestamp).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
          </span>
        )}
      </div>
    </div>
  );
}