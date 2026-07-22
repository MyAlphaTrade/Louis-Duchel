import React, { useState } from "react";
import { base44 } from "@/api/base44Client";
import { Link } from "react-router-dom";
import { Mail } from "lucide-react";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await base44.auth.resetPasswordRequest(email);
    } catch {}
    setSent(true);
    setLoading(false);
  };

  return (
    <div className="min-h-screen bg-[#0a0e17] flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-amber-400 to-amber-600 mb-4 overflow-hidden">
            <img src="/logo-white.png" alt="AlphaTrade" className="w-full h-full object-cover" />
          </div>
          <h1 className="text-2xl font-bold text-white font-heading">Mot de passe oublié</h1>
          <p className="text-slate-500 text-sm mt-1">Recevez un lien de réinitialisation par email</p>
        </div>

        {sent ? (
          <div className="text-center space-y-4">
            <p className="text-sm text-slate-400">Si un compte existe avec cet email, un lien de réinitialisation a été envoyé.</p>
            <Link to="/login" className="inline-block text-amber-400 hover:text-amber-300 text-sm font-medium">
              Retour à la connexion
            </Link>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="relative">
              <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
              <input type="email" placeholder="Votre email" value={email} onChange={(e) => setEmail(e.target.value)} required className="w-full pl-11 pr-4 py-3 rounded-xl bg-[#0d1220] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40 transition-colors" />
            </div>
            <button type="submit" disabled={loading} className="w-full py-3 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-[#0a0e17] font-semibold text-sm disabled:opacity-50 transition-all">
              {loading ? "Envoi…" : "Envoyer le lien"}
            </button>
            <p className="text-xs text-slate-600 text-center">
              <Link to="/login" className="text-amber-400 hover:text-amber-300">Retour à la connexion</Link>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}