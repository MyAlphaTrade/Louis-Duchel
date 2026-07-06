from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import joblib
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import balanced_accuracy_score
    from sklearn.model_selection import TimeSeriesSplit
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False


SERVER_VERSION = "4.0.0"
DATA_DIR = Path(os.environ.get("ALPHATRADE_DATA_DIR", Path.home() / "AlphaTrade"))
API_TOKEN = os.environ.get("ALPHATRADE_AI_TOKEN", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("ALPHATRADE_OPENAI_MODEL", "gpt-4.1-mini").strip()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.environ.get("ALPHATRADE_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001").strip()
SERVER_DIR = DATA_DIR / "ai-server"
MODEL_DIR = SERVER_DIR / "models"
DB_PATH = SERVER_DIR / "ai_server.db"
FEATURE_NAMES = [
    "return_1", "return_3", "return_8",
    "ema_gap_fast", "ema_gap_slow",
    "rsi", "macd", "range_position", "volatility",
]
MODEL_CACHE: dict[str, tuple[object, dict]] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_conn() -> sqlite3.Connection:
    SERVER_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS models (
            symbol TEXT NOT NULL, version INTEGER NOT NULL,
            trained_at TEXT NOT NULL, samples INTEGER NOT NULL,
            score REAL NOT NULL, active INTEGER NOT NULL,
            artifact TEXT NOT NULL, metrics_json TEXT NOT NULL,
            PRIMARY KEY(symbol, version)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observed_at TEXT NOT NULL, symbol TEXT NOT NULL,
            local_signal TEXT, local_confidence REAL,
            server_signal TEXT, server_confidence REAL,
            agreement INTEGER, payload_json TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def ema(values: list[float], period: int) -> float:
    alpha = 2.0 / (period + 1.0)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    deltas = [c - p for p, c in zip(values[-period - 1: -1], values[-period:])]
    gains = sum(max(d, 0.0) for d in deltas) / period
    losses = sum(max(-d, 0.0) for d in deltas) / period
    return 100.0 if losses == 0 else 100.0 - 100.0 / (1.0 + gains / losses)


def candle_features(candles: list[dict], end: int) -> list[float] | None:
    if not ML_AVAILABLE or end < 55:
        return None
    window = candles[: end + 1]
    closes = [float(item["close"]) for item in window]
    highs = [float(item["high"]) for item in window[-20:]]
    lows = [float(item["low"]) for item in window[-20:]]
    current = closes[-1]
    if current == 0:
        return None
    span = max(highs) - min(lows)
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(-19, 0) if closes[i - 1]]
    return [
        (current - closes[-2]) / closes[-2] if closes[-2] else 0.0,
        (current - closes[-4]) / closes[-4] if closes[-4] else 0.0,
        (current - closes[-9]) / closes[-9] if closes[-9] else 0.0,
        (ema(closes[-30:], 5) - ema(closes[-40:], 13)) / current,
        (ema(closes[-50:], 20) - ema(closes[-55:], 50)) / current,
        rsi(closes, 14) / 100.0,
        (ema(closes[-35:], 12) - ema(closes[-35:], 26)) / current,
        (current - min(lows)) / span if span > 0 else 0.5,
        float(np.std(returns)) if returns else 0.0,
    ]


def training_matrix(candles: list[dict], horizon: int):
    rows: list[list[float]] = []
    labels: list[str] = []
    for index in range(55, len(candles) - horizon):
        features = candle_features(candles, index)
        if features is None:
            continue
        current = float(candles[index]["close"])
        future = float(candles[index + horizon]["close"])
        recent_ranges = [float(c["high"]) - float(c["low"]) for c in candles[max(0, index - 13): index + 1]]
        noise = max(float(np.mean(recent_ranges)) * 0.12, current * 0.00001)
        move = future - current
        if abs(move) < noise:
            continue
        rows.append(features)
        labels.append("BUY" if move > 0 else "SELL")
    return np.asarray(rows, dtype=float), np.asarray(labels)


def active_model(conn: sqlite3.Connection, symbol: str) -> dict | None:
    row = conn.execute(
        "SELECT symbol,version,trained_at,samples,score,artifact,metrics_json "
        "FROM models WHERE symbol=? AND active=1 ORDER BY version DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if not row:
        return None
    return {
        "symbol": row[0], "version": int(row[1]), "trained_at": row[2],
        "samples": int(row[3]), "score": float(row[4]),
        "artifact": row[5], "metrics": json.loads(row[6]),
    }


def model_for(conn: sqlite3.Connection, symbol: str) -> tuple[object, dict] | None:
    if not ML_AVAILABLE:
        return None
    active = active_model(conn, symbol)
    if not active:
        return None
    cached = MODEL_CACHE.get(symbol)
    if cached and int(cached[1]["version"]) == int(active["version"]):
        return cached
    artifact = Path(active["artifact"])
    if not artifact.exists():
        return None
    loaded = joblib.load(artifact)
    MODEL_CACHE[symbol] = (loaded, active)
    return MODEL_CACHE[symbol]


def train_symbol(conn: sqlite3.Connection, symbol: str, candles: list[dict], horizon: int) -> dict:
    if not ML_AVAILABLE:
        return {"ok": False, "reason": "ML packages (numpy/scikit-learn/joblib) non installes."}
    x_values, y_values = training_matrix(candles, horizon)
    if len(x_values) < 120 or len(set(y_values.tolist())) < 2:
        return {"ok": False, "reason": "Echantillon insuffisant.", "samples": int(len(x_values))}
    splitter = TimeSeriesSplit(n_splits=4)
    fold_scores = []
    for train_idx, test_idx in splitter.split(x_values):
        candidate = RandomForestClassifier(
            n_estimators=120, max_depth=7, min_samples_leaf=5,
            class_weight="balanced", random_state=42, n_jobs=-1,
        )
        candidate.fit(x_values[train_idx], y_values[train_idx])
        fold_scores.append(balanced_accuracy_score(y_values[test_idx], candidate.predict(x_values[test_idx])))
    score = float(np.mean(fold_scores))
    model = RandomForestClassifier(
        n_estimators=180, max_depth=7, min_samples_leaf=5,
        class_weight="balanced", random_state=42, n_jobs=-1,
    )
    model.fit(x_values, y_values)
    previous = active_model(conn, symbol)
    version = int(conn.execute(
        "SELECT COALESCE(MAX(version),0)+1 FROM models WHERE symbol=?", (symbol,)
    ).fetchone()[0])
    promote = (previous is None and score >= 0.50) or (
        previous is not None and score >= max(0.50, float(previous["score"]) + 0.005)
    )
    artifact = MODEL_DIR / f"{symbol.lower()}-v{version}.joblib"
    joblib.dump(model, artifact)
    metrics = {
        "balanced_accuracy": round(score, 4),
        "fold_scores": [round(v, 4) for v in fold_scores],
        "features": FEATURE_NAMES, "horizon_bars": horizon,
        "classes": model.classes_.tolist(),
    }
    if promote:
        conn.execute("UPDATE models SET active=0 WHERE symbol=?", (symbol,))
    conn.execute(
        "INSERT INTO models(symbol,version,trained_at,samples,score,active,artifact,metrics_json) VALUES(?,?,?,?,?,?,?,?)",
        (symbol, version, utc_now(), int(len(x_values)), score, 1 if promote else 0, str(artifact), json.dumps(metrics, ensure_ascii=True)),
    )
    conn.commit()
    if promote:
        MODEL_CACHE[symbol] = (model, active_model(conn, symbol))
    return {"ok": True, "promoted": promote, "candidate_version": version,
            "samples": int(len(x_values)), "score": round(score, 4), "active_model": active_model(conn, symbol)}


def predict_symbol(conn: sqlite3.Connection, symbol: str, candles: list[dict], local: dict) -> dict:
    if not ML_AVAILABLE:
        return {"available": False, "reason": "ML packages non installes."}
    loaded = model_for(conn, symbol)
    if not loaded:
        return {"available": False, "reason": "Aucun modele valide."}
    model, metadata = loaded
    features = candle_features(candles, len(candles) - 1)
    if features is None:
        return {"available": False, "reason": "Bougies insuffisantes."}
    probabilities = model.predict_proba(np.asarray([features], dtype=float))[0]
    scores = {str(label): float(value) for label, value in zip(model.classes_, probabilities)}
    signal = max(scores, key=scores.get)
    confidence = scores[signal] * 100.0
    local_signal = str(local.get("signal") or "WAIT")
    conn.execute(
        "INSERT INTO observations(observed_at,symbol,local_signal,local_confidence,server_signal,server_confidence,agreement,payload_json) VALUES(?,?,?,?,?,?,?,?)",
        (utc_now(), symbol, local_signal, float(local.get("confidence") or 0), signal, confidence,
         1 if signal == local_signal else 0, json.dumps({"features": features, "scores": scores}, ensure_ascii=True)),
    )
    conn.commit()
    return {
        "available": True, "mode": "OBSERVATION", "signal": signal,
        "confidence": round(confidence, 1),
        "scores": {k: round(v * 100.0, 1) for k, v in scores.items()},
        "agrees_with_local": signal == local_signal, "model": metadata,
    }


def models_payload(conn: sqlite3.Connection) -> dict:
    return {
        "server_version": SERVER_VERSION,
        "ml_available": ML_AVAILABLE,
        "models": {s: active_model(conn, s) for s in ("XAUUSD", "BOOM1000", "CRASH1000")},
    }


def compact_context(payload: dict) -> dict:
    context = dict(payload.get("context") or {})
    status = dict(context.get("status") or {})
    question = str(payload.get("question") or "").strip()
    return {
        "question": question,
        "active_symbol": status.get("active_symbol"),
        "mode": status.get("mode"),
        "balance": status.get("balance"),
        "equity": status.get("equity"),
        "analysis": (status.get("analysis") or {}).get(status.get("active_symbol")),
        "decision": status.get("simulated_decision"),
        "protection": status.get("protection"),
        "positions": [
            {"symbol": p.get("symbol"), "origin": p.get("origin"),
             "direction": p.get("direction"), "lot": p.get("lot"), "profit": p.get("profit")}
            for p in list(status.get("positions") or [])[:8]
        ],
        "recent_trades": [
            {"symbol": t.get("symbol"), "type": t.get("type"),
             "lot": t.get("lot"), "profit": t.get("profit")}
            for t in list(context.get("trades") or [])[:12]
        ],
        "params": {
            "active_symbol": (context.get("params") or {}).get("active_symbol"),
            "trading_enabled": (context.get("params") or {}).get("trading_enabled"),
        },
    }


SYSTEM_CHAT = (
    "Tu es AlphaTrade IA, l'assistant intelligent integre a l'application AlphaTrade. "
    "Tu reponds en francais clair, comme un copilote de trading prudent. "
    "Tu raisonnes a partir du contexte JSON fourni: MT5, signal, positions, protections, parametres et historique. "
    "Tu ne garantis jamais de profit. Tu peux expliquer pourquoi un trade est refuse, quelles conditions manquent, "
    "et quelles corrections sont possibles. "
    "Si une action de trading est demandee, explique les conditions; ne pretend pas avoir ouvert une position toi-meme."
)

SYSTEM_DECISION = (
    "Tu es AlphaTrade IA-Decision, un validateur prudent pour un bot MT5. "
    "Tu recois un contexte JSON compact: symbole, indicateurs, decision locale, protections, positions et parametres. "
    "Tu ne peux PAS ouvrir, fermer ou modifier une position. Le moteur local garde toujours la securite finale. "
    "Ta tache: confirmer ou bloquer une entree candidate. "
    "Reponds uniquement en JSON valide, sans markdown, avec les champs exacts: "
    "ok(bool), approved(bool), decision('BUY'|'SELL'|'WAIT'), confidence(number 0-100), reason(string), risk_notes(array string). "
    "approved doit etre true seulement si la decision est BUY ou SELL, coherente avec la decision locale candidate, "
    "et si le risque est acceptable. "
    "Si le marche semble trop extreme, confus, en range dangereux, ou si la decision locale est faible, "
    "retourne WAIT et approved false. Ne promets jamais de profit."
)


def _extract_text_openai(data: dict) -> str:
    text = data.get("output_text")
    if text:
        return str(text).strip()
    chunks: list[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(str(content["text"]))
    return "\n".join(chunks).strip()


def _extract_text_anthropic(data: dict) -> str:
    chunks: list[str] = []
    for block in data.get("content", []) or []:
        if block.get("type") == "text" and block.get("text"):
            chunks.append(str(block["text"]))
    return "\n".join(chunks).strip()


def _parse_decision_json(text: str) -> dict:
    cleaned = text.strip().strip("`")
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start: end + 1]
    return json.loads(cleaned)


def openai_chat(payload: dict) -> dict:
    if not OPENAI_API_KEY:
        return {"ok": False, "error": "OPENAI_API_KEY manquante.", "fallback": True}
    context = compact_context(payload)
    if not context["question"]:
        return {"ok": False, "error": "Question vide.", "fallback": True}
    body = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": SYSTEM_CHAT},
            {"role": "user", "content": "Question: " + context["question"] + "\n\nContexte JSON:\n" + json.dumps(context, ensure_ascii=False)},
        ],
        "max_output_tokens": 700,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = _extract_text_openai(data)
        return {"ok": True, "provider": "openai", "model": data.get("model") or OPENAI_MODEL,
                "answer": text or "Aucun texte recu.", "usage": data.get("usage") or {}}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "provider": "openai", "error": f"OpenAI HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:400]}", "fallback": True}
    except Exception as exc:
        return {"ok": False, "provider": "openai", "error": str(exc), "fallback": True}


def anthropic_chat(payload: dict) -> dict:
    if not ANTHROPIC_API_KEY:
        return {"ok": False, "error": "ANTHROPIC_API_KEY manquante.", "fallback": True}
    context = compact_context(payload)
    if not context["question"]:
        return {"ok": False, "error": "Question vide.", "fallback": True}
    body = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 700,
        "system": SYSTEM_CHAT,
        "messages": [
            {"role": "user", "content": "Question: " + context["question"] + "\n\nContexte JSON:\n" + json.dumps(context, ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = _extract_text_anthropic(data)
        return {"ok": True, "provider": "anthropic", "model": data.get("model") or ANTHROPIC_MODEL,
                "answer": text or "Aucun texte recu.", "usage": data.get("usage") or {}}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "provider": "anthropic", "error": f"Anthropic HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:400]}", "fallback": True}
    except Exception as exc:
        return {"ok": False, "provider": "anthropic", "error": str(exc), "fallback": True}


def openai_trade_decision(payload: dict) -> dict:
    if not OPENAI_API_KEY:
        return {"ok": False, "approved": False, "decision": "WAIT", "confidence": 0,
                "reason": "OPENAI_API_KEY manquante.", "risk_notes": ["Cle API absente"], "fallback": True}
    context = dict(payload.get("context") or {})
    local_signal = str((context.get("local_decision") or {}).get("signal") or "WAIT").upper()
    body = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": SYSTEM_DECISION},
            {"role": "user", "content": "Decision locale candidate: " + local_signal + "\nContexte:\n" + json.dumps(context, ensure_ascii=False)},
        ],
        "max_output_tokens": 450,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parsed = _parse_decision_json(_extract_text_openai(data))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "approved": False, "decision": "WAIT", "confidence": 0,
                "reason": f"OpenAI HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}",
                "risk_notes": ["Erreur serveur OpenAI"], "fallback": True, "provider": "openai"}
    except Exception as exc:
        return {"ok": False, "approved": False, "decision": "WAIT", "confidence": 0,
                "reason": str(exc), "risk_notes": ["Reponse invalide"], "fallback": True, "provider": "openai"}
    decision = str(parsed.get("decision") or "WAIT").upper()
    if decision not in {"BUY", "SELL", "WAIT"}:
        decision = "WAIT"
    confidence = max(0.0, min(100.0, float(parsed.get("confidence") or 0)))
    approved = bool(parsed.get("approved")) and decision in {"BUY", "SELL"} and decision == local_signal
    return {"ok": True, "provider": "openai", "approved": approved, "decision": decision,
            "confidence": round(confidence, 1), "reason": str(parsed.get("reason") or ""),
            "risk_notes": list(parsed.get("risk_notes") or [])[:6], "model": data.get("model") or OPENAI_MODEL}


def anthropic_trade_decision(payload: dict) -> dict:
    if not ANTHROPIC_API_KEY:
        return {"ok": False, "approved": False, "decision": "WAIT", "confidence": 0,
                "reason": "ANTHROPIC_API_KEY manquante.", "risk_notes": ["Cle API absente"], "fallback": True}
    context = dict(payload.get("context") or {})
    local_signal = str((context.get("local_decision") or {}).get("signal") or "WAIT").upper()
    body = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 450,
        "system": SYSTEM_DECISION,
        "messages": [
            {"role": "user", "content": "Decision locale candidate: " + local_signal + "\nContexte:\n" + json.dumps(context, ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parsed = _parse_decision_json(_extract_text_anthropic(data))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "approved": False, "decision": "WAIT", "confidence": 0,
                "reason": f"Anthropic HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}",
                "risk_notes": ["Erreur serveur Anthropic"], "fallback": True, "provider": "anthropic"}
    except Exception as exc:
        return {"ok": False, "approved": False, "decision": "WAIT", "confidence": 0,
                "reason": str(exc), "risk_notes": ["Reponse invalide"], "fallback": True, "provider": "anthropic"}
    decision = str(parsed.get("decision") or "WAIT").upper()
    if decision not in {"BUY", "SELL", "WAIT"}:
        decision = "WAIT"
    confidence = max(0.0, min(100.0, float(parsed.get("confidence") or 0)))
    approved = bool(parsed.get("approved")) and decision in {"BUY", "SELL"} and decision == local_signal
    return {"ok": True, "provider": "anthropic", "approved": approved, "decision": decision,
            "confidence": round(confidence, 1), "reason": str(parsed.get("reason") or ""),
            "risk_notes": list(parsed.get("risk_notes") or [])[:6], "model": data.get("model") or ANTHROPIC_MODEL}


def dual_trade_decision(payload: dict) -> dict:
    results = []
    if ANTHROPIC_API_KEY:
        results.append(anthropic_trade_decision(payload))
    if OPENAI_API_KEY:
        results.append(openai_trade_decision(payload))
    if not results:
        return {"ok": False, "approved": False, "decision": "WAIT", "confidence": 0,
                "reason": "Aucune cle API configuree (OPENAI_API_KEY ou ANTHROPIC_API_KEY).",
                "risk_notes": ["Aucune cle API"], "fallback": True}
    if len(results) == 1:
        return results[0]
    ok_results = [r for r in results if r.get("ok")]
    if not ok_results:
        return results[0]
    if len(ok_results) == 1:
        return ok_results[0]
    # Les deux ont repondu : consensus requis
    decisions = [r["decision"] for r in ok_results]
    if len(set(decisions)) == 1:
        # Accord parfait
        approved = all(r.get("approved") for r in ok_results)
        confidence = round(sum(r["confidence"] for r in ok_results) / len(ok_results), 1)
        reason = " | ".join(f"[{r['provider'].upper()}] {r['reason']}" for r in ok_results)
        return {
            "ok": True, "approved": approved, "decision": decisions[0],
            "confidence": confidence, "reason": reason,
            "risk_notes": ok_results[0].get("risk_notes", []),
            "providers": [r["provider"] for r in ok_results],
            "consensus": True,
        }
    else:
        # Desaccord : prudence -> WAIT
        reason = "Desaccord entre les deux IA (" + " vs ".join(
            f"{r['provider'].upper()}:{r['decision']}" for r in ok_results
        ) + "). Entree bloquee par precaution."
        return {
            "ok": True, "approved": False, "decision": "WAIT", "confidence": 0,
            "reason": reason,
            "risk_notes": ["Desaccord IA OpenAI/Anthropic — attente de consensus"],
            "providers": [r["provider"] for r in ok_results],
            "consensus": False,
        }


def best_chat(payload: dict) -> dict:
    if ANTHROPIC_API_KEY:
        result = anthropic_chat(payload)
        if result.get("ok"):
            return result
    if OPENAI_API_KEY:
        result = openai_chat(payload)
        if result.get("ok"):
            return result
    return {"ok": False, "error": "Aucune cle API configuree (OPENAI_API_KEY ou ANTHROPIC_API_KEY).",
            "fallback": True}


class Handler(BaseHTTPRequestHandler):
    server_version = f"AlphaTradeAI/{SERVER_VERSION}"

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        size = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(size).decode("utf-8")) if size else {}

    def authorized(self) -> bool:
        if not API_TOKEN:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {API_TOKEN}"

    def do_GET(self) -> None:
        if self.path != "/health" and not self.authorized():
            self.send_json(401, {"ok": False, "error": "Unauthorized"})
            return
        conn = db_conn()
        try:
            if self.path == "/health":
                self.send_json(200, {
                    "ok": True,
                    "version": SERVER_VERSION,
                    "time": int(time.time()),
                    "openai_ready": bool(OPENAI_API_KEY),
                    "anthropic_ready": bool(ANTHROPIC_API_KEY),
                    "dual_validation": bool(OPENAI_API_KEY and ANTHROPIC_API_KEY),
                    "ml_available": ML_AVAILABLE,
                    "openai_model": OPENAI_MODEL if OPENAI_API_KEY else None,
                    "anthropic_model": ANTHROPIC_MODEL if ANTHROPIC_API_KEY else None,
                })
            elif self.path == "/v1/models":
                self.send_json(200, models_payload(conn))
            else:
                self.send_json(404, {"ok": False, "error": "Not found"})
        finally:
            conn.close()

    def do_OPTIONS(self) -> None:
        self.send_json(204, {})

    def do_POST(self) -> None:
        if not self.authorized():
            self.send_json(401, {"ok": False, "error": "Unauthorized"})
            return
        conn = db_conn()
        try:
            payload = self.read_json()
            if self.path == "/v1/train":
                self.send_json(200, train_symbol(conn, str(payload.get("symbol") or ""),
                                                 list(payload.get("candles") or []),
                                                 max(1, int(payload.get("horizon_bars") or 3))))
            elif self.path == "/v1/predict":
                self.send_json(200, predict_symbol(conn, str(payload.get("symbol") or ""),
                                                   list(payload.get("candles") or []),
                                                   dict(payload.get("local") or {})))
            elif self.path == "/v1/chat":
                self.send_json(200, best_chat(payload))
            elif self.path == "/v1/decision":
                self.send_json(200, dual_trade_decision(payload))
            else:
                self.send_json(404, {"ok": False, "error": "Not found"})
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})
        finally:
            conn.close()

    def log_message(self, format_string: str, *args) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="AlphaTrade AI server v4")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    args = parser.parse_args()
    db_conn().close()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    providers = []
    if OPENAI_API_KEY:
        providers.append(f"OpenAI/{OPENAI_MODEL}")
    if ANTHROPIC_API_KEY:
        providers.append(f"Anthropic/{ANTHROPIC_MODEL}")
    status = ("dual-validation" if len(providers) == 2 else providers[0]) if providers else "no-key"
    print(f"AlphaTrade AI server {SERVER_VERSION} on {args.host}:{args.port} [{status}]", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
