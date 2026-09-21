"""Empreintes et verifications d'integrite -- D3 / D5 / D6 (verrouilles,
2026-09-19/20).

Empreinte d'une serie de bougies : bougies triees par `timestamp` (ordre
strictement croissant, sinon erreur) ; pour chacune la ligne
`timestamp|open|high|low|close` + saut de ligne LF, valeurs telles que
stockees (representation Python par defaut) ; SHA-256 de la concatenation
encodee en UTF-8.

REFERENCE HISTORIQUE (D3, corrigee le 2026-09-19) : bougies M15 US Tech 100
jusqu'a `2026-09-16T00:30:00Z` -- la derniere bougie CLOTUREE au moment de
l'import initial du 16/09 a 00:47:17 UTC. La bougie de 00:45, encore en
formation a cet instant, est explicitement HORS reference. L'ancienne
empreinte (bc66e254...) est abandonnee. Cette reference verifie que la
portion historique reste identique ; elle n'est pas l'empreinte de la serie
complete apres ajout de nouvelles bougies.

Hash probant d'un fichier suivi par git (D6) : SHA-256 du contenu tel que
git le stocke, donc avec fins de ligne LF (core.autocrlf=true sur cette
machine : le fichier de travail peut etre en CRLF). Verification :
    git show <commit>:"<chemin>" | sha256sum

Module pur : aucun acces DB.
"""
import hashlib

REFERENCE_N = 62521
REFERENCE_LAST_BAR = "2026-09-16T00:30:00Z"
REFERENCE_SHA256 = "fb13b6221d7ca1382854da26b430d41d150cd1084a40e181a10eaea5533a10bc"


def bars_fingerprint(bars, up_to_ts=None):
    """Retourne (n, sha256_hex). `up_to_ts` : borne haute incluse (ISO
    canonique). Leve ValueError si les bougies ne sont pas strictement
    croissantes par timestamp."""
    h = hashlib.sha256()
    n = 0
    previous = None
    for b in bars:
        ts = b["timestamp"]
        if previous is not None and ts <= previous:
            raise ValueError(f"Bougies non strictement croissantes : {previous} puis {ts}.")
        previous = ts
        if up_to_ts is not None and ts > up_to_ts:
            continue
        h.update(f'{ts}|{b["open"]}|{b["high"]}|{b["low"]}|{b["close"]}\n'.encode("utf-8"))
        n += 1
    return n, h.hexdigest()


def reference_series(bars, last_bar=REFERENCE_LAST_BAR):
    """Serie HISTORIQUE utilisee par les analyses D4/D7 : les bougies dont le
    timestamp est <= la derniere bougie de reference, rien d'autre. Toute
    bougie posterieure (partielle ou non, prospective ou non) en est exclue,
    de sorte qu'aucun import ulterieur ne peut modifier ces analyses."""
    return [b for b in bars if b["timestamp"] <= last_bar]


def verify_reference(bars, expected_n=REFERENCE_N, expected_last=REFERENCE_LAST_BAR, expected_sha256=REFERENCE_SHA256):
    """Verifie que la portion historique couverte par la reference est
    inchangee (nombre, derniere bougie, SHA-256)."""
    n, sha = bars_fingerprint(bars, up_to_ts=expected_last)
    last = None
    for b in bars:
        if b["timestamp"] <= expected_last:
            last = b["timestamp"]
    return {
        "ok": n == expected_n and last == expected_last and sha == expected_sha256,
        "n": n, "expected_n": expected_n,
        "last_bar": last, "expected_last_bar": expected_last,
        "sha256": sha, "expected_sha256": expected_sha256,
    }


def sha256_lf_normalized(data: bytes) -> str:
    """SHA-256 du contenu avec fins de ligne CRLF ramenees a LF -- ce que
    git stocke dans le blob."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def file_sha256_lf(path) -> str:
    with open(path, "rb") as f:
        return sha256_lf_normalized(f.read())


def sidecar_text(sha256_hex: str, filename: str) -> str:
    """Contenu du fichier `<nom>.sha256` (format `hash  nom`, LF)."""
    return f"{sha256_hex}  {filename}\n"
