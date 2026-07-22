import React, { createContext, useContext, useState } from "react";
import { base44 } from "@/api/base44Client";

// AlphaTradeConnectionContext — Export Signaux (Module 5).
//
// Pont deliberement etroit vers AlphaTrade (le seul endroit ou Strategy Lab
// sort de son isolation) : email/mot de passe AlphaTrade ne transitent que le
// temps de l'appel de connexion (relaye tel quel par notre backend, jamais
// stocke) ; seul le jeton obtenu en retour est garde (localStorage, via
// base44Client.js, meme principe BYOK que la cle API IA). Se deconnecter ici
// n'affecte jamais la session AlphaTrade elle-meme sur l'ordinateur.

const STORAGE_KEY = "strategylab:alphatradeConnection";
const AlphaTradeConnectionContext = createContext(null);

function loadConnectionInfo() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveConnectionInfo(info) {
  try {
    if (info) localStorage.setItem(STORAGE_KEY, JSON.stringify(info));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

export function AlphaTradeConnectionProvider({ children }) {
  const [connectedEmail, setConnectedEmail] = useState(() => {
    if (!base44.alphatrade.isConnected()) return null;
    return loadConnectionInfo()?.email || null;
  });
  const [connecting, setConnecting] = useState(false);

  const connect = async (email, password) => {
    setConnecting(true);
    try {
      const user = await base44.alphatrade.login(email, password);
      const resolvedEmail = user?.email || email;
      saveConnectionInfo({ email: resolvedEmail });
      setConnectedEmail(resolvedEmail);
      return user;
    } finally {
      setConnecting(false);
    }
  };

  const disconnect = () => {
    base44.alphatrade.disconnect();
    saveConnectionInfo(null);
    setConnectedEmail(null);
  };

  return (
    <AlphaTradeConnectionContext.Provider
      value={{
        connected: Boolean(connectedEmail) && base44.alphatrade.isConnected(),
        connectedEmail,
        connecting,
        connect,
        disconnect,
      }}
    >
      {children}
    </AlphaTradeConnectionContext.Provider>
  );
}

export function useAlphaTradeConnection() {
  const ctx = useContext(AlphaTradeConnectionContext);
  if (!ctx) throw new Error("useAlphaTradeConnection must be used within AlphaTradeConnectionProvider");
  return ctx;
}
