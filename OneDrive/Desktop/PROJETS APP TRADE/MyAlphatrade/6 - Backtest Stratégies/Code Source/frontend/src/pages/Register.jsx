import React, { useState } from "react";
import { base44 } from "@/api/base44Client";
import { Link } from "react-router-dom";
import { Mail, Lock, Eye, EyeOff, User } from "lucide-react";

export default function Register() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleRegister = async (e) => {
    e.preventDefault();
    setError("");
    if (password !== confirmPassword) {
      setError("Les mots de passe ne correspondent pas.");
      return;
    }
    setLoading(true);
    try {
      // Le backend (POST /auth/register) authentifie directement et renvoie un
      // token, sans étape de vérification par email : redirection directe vers
      // l'app, comme le fait Login.jsx après connexion.
      await base44.auth.register({ email, password, full_name: fullName });
      window.location.href = "/";
    } catch (err) {
      setError(err.message || "Erreur lors de l'inscription.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0a0e17] flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-amber-400 to-amber-600 mb-4 overflow-hidden">
            <img src="/logo-white.png" alt="AlphaTrade" className="w-full h-full object-cover" />
          </div>
          <h1 className="text-2xl font-bold text-white font-heading">AlphaTrade</h1>
          <p className="text-slate-500 text-sm mt-1">Créer votre compte</p>
        </div>

        <form onSubmit={handleRegister} className="space-y-4">
          <div className="relative">
            <User className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input type="text" placeholder="Nom complet" value={fullName} onChange={(e) => setFullName(e.target.value)} required className="w-full pl-11 pr-4 py-3 rounded-xl bg-[#0d1220] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40 transition-colors" />
          </div>
          <div className="relative">
            <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required className="w-full pl-11 pr-4 py-3 rounded-xl bg-[#0d1220] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40 transition-colors" />
          </div>
          <div className="relative">
            <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input type={showPassword ? "text" : "password"} placeholder="Mot de passe" value={password} onChange={(e) => setPassword(e.target.value)} required className="w-full pl-11 pr-11 py-3 rounded-xl bg-[#0d1220] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40 transition-colors" />
            <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
              {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
          <div className="relative">
            <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input type="password" placeholder="Confirmer le mot de passe" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required className="w-full pl-11 pr-4 py-3 rounded-xl bg-[#0d1220] border border-[#1a2332] text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-amber-500/40 transition-colors" />
          </div>

          {error && <p className="text-red-400 text-xs text-center">{error}</p>}

          <button type="submit" disabled={loading} className="w-full py-3 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 text-[#0a0e17] font-semibold text-sm hover:from-amber-400 hover:to-amber-500 disabled:opacity-50 transition-all">
            {loading ? "Inscription…" : "Créer un compte"}
          </button>
        </form>

        <p className="mt-6 text-xs text-slate-600 text-center">
          Déjà un compte ?{" "}
          <Link to="/login" className="text-amber-400 hover:text-amber-300 font-medium">Se connecter</Link>
        </p>
      </div>
    </div>
  );
}
