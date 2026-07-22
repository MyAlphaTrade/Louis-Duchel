import { API_BASE_URL } from '@/lib/app-params';

// Remplace le SDK @base44/sdk par un client REST minimal contre notre propre
// backend FastAPI (Code Source/backend). L'objet exporté conserve exactement
// la même forme que celle utilisée par les 82 fichiers portés depuis Base44
// (base44.auth.*, base44.entities.<Type>.*) afin qu'aucun d'eux n'ait besoin
// d'être modifié pour consommer ce nouveau client.

const TOKEN_KEY = 'strategylab_token';

function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function setToken(token) {
  try {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    // localStorage indisponible (SSR, navigation privée, etc.) : on ignore.
  }
}

function clearToken() {
  setToken(null);
}

function apiError(status, data, fallbackMessage) {
  const message = (data && (data.detail || data.message)) || fallbackMessage || `Erreur ${status}`;
  const error = new Error(message);
  error.status = status;
  error.data = data;
  return error;
}

async function apiFetch(path, options = {}) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });

  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    throw apiError(res.status, data, `Erreur ${res.status} lors de l'appel à ${path}`);
  }

  return data;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

async function me() {
  return apiFetch('/auth/me');
}

async function login(email, password) {
  const data = await apiFetch('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  if (data?.token) setToken(data.token);
  return data?.user ?? data;
}

// Register.jsx (page portée) appelle base44.auth.register({ email, password }) avec un
// objet, tandis que la forme "historique" attendue par la spec de portage est
// register(email, password, fullName). On supporte les deux formes d'appel.
async function register(emailOrPayload, password, fullName) {
  const payload =
    typeof emailOrPayload === 'object' && emailOrPayload !== null
      ? emailOrPayload
      : { email: emailOrPayload, password, full_name: fullName };

  const email = payload.email;
  const full_name = payload.full_name || payload.fullName || (email ? email.split('@')[0] : '');

  const data = await apiFetch('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password: payload.password, full_name }),
  });
  if (data?.token) setToken(data.token);
  return data?.user ?? data;
}

function logout(redirectUrl) {
  clearToken();
  // Best-effort : on ne bloque pas sur la réponse du backend.
  apiFetch('/auth/logout', { method: 'POST' }).catch(() => {});
  if (redirectUrl) {
    window.location.href = redirectUrl;
  }
}

function redirectToLogin(returnUrl) {
  window.location.href = returnUrl
    ? `/login?return_url=${encodeURIComponent(returnUrl)}`
    : '/login';
}

// Réinitialisation de mot de passe par email (lien avec token), même pattern
// que le backend AlphaTrade existant (Resend + password_reset_tokens).

async function resetPasswordRequest(email) {
  return apiFetch('/auth/forgot-password', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
}

async function resetPassword({ resetToken, newPassword }) {
  return apiFetch('/auth/reset-password', {
    method: 'POST',
    body: JSON.stringify({ token: resetToken, new_password: newPassword }),
  });
}

// ---------------------------------------------------------------------------
// Entities
// ---------------------------------------------------------------------------

function makeEntityClient(entityType) {
  return {
    async list(sort, limit) {
      const params = new URLSearchParams();
      if (sort) params.set('sort', sort);
      if (limit) params.set('limit', String(limit));
      const qs = params.toString();
      return apiFetch(`/entities/${entityType}${qs ? `?${qs}` : ''}`);
    },
    async create(data) {
      return apiFetch(`/entities/${entityType}`, {
        method: 'POST',
        body: JSON.stringify(data),
      });
    },
    async update(id, data) {
      return apiFetch(`/entities/${entityType}/${id}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      });
    },
    async delete(id) {
      return apiFetch(`/entities/${entityType}/${id}`, {
        method: 'DELETE',
      });
    },
    subscribe(_callback) {
      // TODO: temps réel non implémenté, à faire plus tard si besoin
      return () => {};
    },
  };
}

// MarketData a un pattern d'acces different des 5 autres entites (import en
// masse depuis un CSV, lecture triee par timestamp reel plutot que par date
// de creation) -- endpoints dedies cote backend (/market-data/*) plutot que
// le CRUD generique /entities/MarketData.
const marketData = {
  async list(symbol, timeframe, limit) {
    const params = new URLSearchParams({ symbol, timeframe });
    if (limit) params.set('limit', String(limit));
    return apiFetch(`/market-data?${params.toString()}`);
  },
  async import(symbol, timeframe, candles) {
    return apiFetch('/market-data/import', {
      method: 'POST',
      body: JSON.stringify({ symbol, timeframe, candles }),
    });
  },
  async summary() {
    return apiFetch('/market-data/summary');
  },
  // Dernier prix bid/ask reel, lu par le backend directement depuis le
  // terminal MT5 installe sur la machine de l'utilisateur (Module 4 / Paper
  // Trading, mode Live). Peut echouer (503) si MT5 n'est pas ouvert -- les
  // appelants doivent toujours gerer ce cas plutot que de le laisser
  // remonter en erreur non traitee.
  async getLive(symbol) {
    return apiFetch(`/market-data/live?${new URLSearchParams({ symbol }).toString()}`);
  },
};

// ---------------------------------------------------------------------------
// Pont AlphaTrade (Export Signaux, Module 5) -- seule exception deliberee a
// l'isolation de Strategy Lab. Le jeton AlphaTrade est garde en localStorage
// (jamais envoye ailleurs qu'a notre propre backend, qui le relaie tel quel)
// exactement comme la cle API IA dans AISettingsContext -- meme principe BYOK,
// rien n'est jamais stocke cote serveur Strategy Lab.
// ---------------------------------------------------------------------------

const ALPHATRADE_TOKEN_KEY = 'strategylab_alphatrade_token';

function getAlphaTradeToken() {
  try {
    return localStorage.getItem(ALPHATRADE_TOKEN_KEY);
  } catch {
    return null;
  }
}

function setAlphaTradeToken(token) {
  try {
    if (token) localStorage.setItem(ALPHATRADE_TOKEN_KEY, token);
    else localStorage.removeItem(ALPHATRADE_TOKEN_KEY);
  } catch {
    // localStorage indisponible -- on ignore.
  }
}

const alphatrade = {
  isConnected: () => !!getAlphaTradeToken(),
  disconnect: () => setAlphaTradeToken(null),
  async login(email, password) {
    const data = await apiFetch('/alphatrade/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    if (data?.token) setAlphaTradeToken(data.token);
    return data?.user ?? null;
  },
  async sendSignal(signal) {
    const alphatrade_token = getAlphaTradeToken();
    if (!alphatrade_token) {
      throw apiError(401, null, "Non connecte a AlphaTrade -- reconnectez-vous depuis Parametres.");
    }
    return apiFetch('/alphatrade/send-signal', {
      method: 'POST',
      body: JSON.stringify({ ...signal, alphatrade_token }),
    });
  },
};

export const base44 = {
  auth: {
    me,
    logout,
    redirectToLogin,
    login,
    // Alias : Login.jsx (page portée) appelle historiquement loginViaEmailPassword.
    loginViaEmailPassword: login,
    register,
    resetPasswordRequest,
    resetPassword,
    setToken,
    getToken,
    hasToken: () => !!getToken(),
  },
  marketData,
  alphatrade,
  entities: {
    TradingAsset: makeEntityClient('TradingAsset'),
    Strategy: makeEntityClient('Strategy'),
    BacktestResult: makeEntityClient('BacktestResult'),
    PaperTrade: makeEntityClient('PaperTrade'),
    Signal: makeEntityClient('Signal'),
    // MarketData n'est PAS expose ici : le CRUD generique trie par date de
    // creation, ce qui ne garantit pas l'ordre chronologique des bougies
    // (un import en masse leur donne toutes la meme created_date). Utiliser
    // base44.marketData.* (endpoints dedies, tries par le vrai timestamp).
  },
};
