"""Tests pour l'optimisation du pipeline temps reel MT5<->AlphaTrade (v5.1.1,
06/08/2026) -- demande explicite de Louis suite a l'audit de latence :
params.json ne doit plus etre relu depuis le disque a chaque cycle de la
boucle principale (~10x/seconde) quand rien n'a change, et log() ne doit
plus jamais bloquer le thread de trading sur une ecriture disque."""
import os
import tempfile
import time

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae


def test_cached_params_json_returns_same_object_until_file_changes():
    """Deux appels consecutifs sans modification du fichier doivent renvoyer
    EXACTEMENT le meme objet (aucune relecture disque) -- puis un nouvel
    objet des que le fichier change reellement."""
    ae._PARAMS_JSON_CACHE["mtime"] = None
    ae._PARAMS_JSON_CACHE["data"] = {}
    ae.write_json("params.json", {"risk_pct": 0.5})
    first = ae._cached_params_json()
    second = ae._cached_params_json()
    assert first is second, "Sans modification du fichier, le cache doit renvoyer le meme objet (pas de relecture disque)."
    assert first["risk_pct"] == 0.5

    time.sleep(0.05)  # garantir un mtime different sur les systemes a faible resolution
    ae.write_json("params.json", {"risk_pct": 0.9})
    third = ae._cached_params_json()
    assert third is not first, "Apres une vraie modification du fichier, le cache doit se rafraichir."
    assert third["risk_pct"] == 0.9
    print("test_cached_params_json_returns_same_object_until_file_changes OK")


def test_merge_params_reflects_cache_refresh():
    """merge_params() (le vrai point d'entree utilise par la boucle) doit lui
    aussi refleter un changement de params.json des le prochain appel."""
    ae._PARAMS_JSON_CACHE["mtime"] = None
    ae._PARAMS_JSON_CACHE["data"] = {}
    ae.write_json("params.json", {"risk_pct": 0.42})
    merged = ae.merge_params()
    assert merged["risk_pct"] == 0.42
    time.sleep(0.05)
    ae.write_json("params.json", {"risk_pct": 1.1})
    merged2 = ae.merge_params()
    assert merged2["risk_pct"] == 1.1
    print("test_merge_params_reflects_cache_refresh OK")


def test_log_does_not_block_on_disk_write():
    """log() doit deposer la ligne dans une file et revenir immediatement --
    l'ecriture disque reelle se fait dans le thread dedie, pas dans l'appel."""
    ae.log("test message pour verifier la file de logs", "INFO")
    # La ligne doit finir par arriver sur le disque (thread dedie), meme si
    # log() lui-meme n'a pas attendu l'ecriture.
    log_path = ae.DATA_DIR / "alphatrade.log"
    deadline = time.time() + 2.0
    found = False
    while time.time() < deadline:
        if log_path.exists() and "test message pour verifier la file de logs" in log_path.read_text(encoding="utf-8"):
            found = True
            break
        time.sleep(0.02)
    assert found, "La ligne de log doit finir par etre ecrite sur le disque par le thread dedie."
    print("test_log_does_not_block_on_disk_write OK")


if __name__ == "__main__":
    test_cached_params_json_returns_same_object_until_file_changes()
    test_merge_params_reflects_cache_refresh()
    test_log_does_not_block_on_disk_write()
    print("ALL OK")
