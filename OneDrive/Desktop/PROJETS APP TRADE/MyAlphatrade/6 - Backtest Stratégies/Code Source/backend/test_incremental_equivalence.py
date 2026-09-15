"""Test decisif -- Research Lab Phase 3, ETAPE 4 (2026-09-15).

    ajout incrementbal == recalcul complet

Utilise le dataset REEL fige en etape 3 (DatasetVersion XAUUSD M15,
frozen=true, 3400 bougies, 01/06/2026-22/07/2026 -- voir test_fixtures/
xauusd_m15_frozen_pilot.json, extrait en lecture seule depuis la base
reelle de Louis) comme cas de test, PAS des donnees synthetiques.

Compare le CONTENU (chaque timestamp, chaque valeur OHLC/volume/spread),
jamais seulement des compteurs -- exigence explicite de Louis. Deux
scenarios simulent une accumulation "au fil de l'eau" (comme le fera le
futur backfill/SyncState) contre un import unique de tout l'historique
d'un coup, en passant tous les deux par EXACTEMENT la meme fonction pure
`_merge_market_data` (Phase 1, deja testee separement dans
test_merge_market_data.py sur des fixtures synthetiques minimales -- ce
fichier-ci est le test d'ECHELLE REELLE, sur le vrai volume et les vraies
valeurs).

Portee explicite de ce test (voir brief de synchronisation 2026-09-15) :
- Couvre la couche MarketData (donnees brutes) -- c'est la seule couche
  de "memoire construite progressivement" qui existe reellement dans
  Strategy Lab aujourd'hui.
- Ne couvre PAS une couche d'"evenements derives" (FVG/OB/zones) : cette
  couche n'existe pas encore dans Strategy Lab -- elle vit uniquement
  dans le module Market Memory independant (AlphaTrade Global,
  EA_Bridge/research/), un systeme separe qui n'ecrit jamais dans cette
  base. Pretendre la tester ici serait fabriquer une comparaison qui n'a
  pas de sens sur le code reel actuel.
"""
import json
import unittest

from main import Candle, _merge_market_data

with open("test_fixtures/xauusd_m15_frozen_pilot.json", encoding="utf-8") as f:
    FIXTURE = json.load(f)

ALL_CANDLES = [Candle(**row) for row in FIXTURE["candles"]]
SYMBOL, TIMEFRAME = FIXTURE["symbol"], FIXTURE["timeframe"]


def _apply(existing: dict, candles: list, next_id: list) -> tuple:
    """Simule un cycle complet lecture-DB -> fusion -> ecriture-DB pour un
    lot de bougies, en mutant `existing` sur place (comme le ferait
    vraiment /market-data/import-mt5 ou /market-data/import entre deux
    appels). Retourne (inserted_count, updated_collisions, unchanged)."""
    to_insert, to_update, collisions, unchanged = _merge_market_data(
        existing, SYMBOL, TIMEFRAME, candles
    )
    for data in to_insert:
        existing[data["timestamp"]] = (f"id-{next_id[0]}", data)
        next_id[0] += 1
    for entity_id, data in to_update:
        existing[data["timestamp"]] = (entity_id, data)
    return len(to_insert), collisions, unchanged


def _content(existing: dict) -> list:
    """Extrait le contenu comparable (sans les ids, arbitraires), trie par
    timestamp -- pour une comparaison de CONTENU, pas de compteurs."""
    return sorted((data for _id, data in existing.values()), key=lambda d: d["timestamp"])


class TestFullRecomputeBaseline(unittest.TestCase):
    """Etablit la reference : tout l'historique importe en un seul appel."""

    def test_inserts_every_real_bar_with_zero_collision(self):
        existing = {}
        inserted, collisions, unchanged = _apply(existing, ALL_CANDLES, [0])
        self.assertEqual(inserted, FIXTURE["bars_used"])
        self.assertEqual(collisions, 0)
        self.assertEqual(unchanged, 0)
        self.assertEqual(len(existing), FIXTURE["bars_used"])


class TestIncrementalEqualsFullRecompute(unittest.TestCase):
    """Le coeur de l'etape 4 : accumulation par morceaux vs recalcul complet."""

    def setUp(self):
        full_existing = {}
        _apply(full_existing, ALL_CANDLES, [0])
        self.full_content = _content(full_existing)

    def _run_chunked(self, chunks: list) -> list:
        existing = {}
        next_id = [0]
        for chunk in chunks:
            _apply(existing, chunk, next_id)
        return _content(existing)

    def test_seven_sequential_chunks_produce_byte_identical_content(self):
        # Simule ~7 synchronisations successives (comme un backfill/live
        # quotidien reel), chronologiques, sans chevauchement.
        n = len(ALL_CANDLES)
        size = n // 7
        chunks = [ALL_CANDLES[i : i + size] for i in range(0, n, size)]
        self.assertGreaterEqual(len(chunks), 7)  # sanity : le decoupage a bien eu lieu

        chunked_content = self._run_chunked(chunks)

        # 1) meme NOMBRE (compteur) -- necessaire mais pas suffisant
        self.assertEqual(len(chunked_content), len(self.full_content))
        # 2) meme ENSEMBLE de timestamps -- aucune bougie perdue ni dupliquee
        self.assertEqual(
            {d["timestamp"] for d in chunked_content},
            {d["timestamp"] for d in self.full_content},
        )
        # 3) CONTENU rigoureusement identique, champ par champ, bougie par
        # bougie -- la comparaison que Louis a explicitement demandee, pas
        # seulement un comptage.
        self.assertEqual(chunked_content, self.full_content)

    def test_many_small_chunks_produce_byte_identical_content(self):
        # Cas plus dur : decoupage fin (bloc de 50 bougies, ~68 lots) --
        # plus de cycles lecture-fusion-ecriture, plus d'occasions pour un
        # bug de fusion de se reveler.
        n = len(ALL_CANDLES)
        chunks = [ALL_CANDLES[i : i + 50] for i in range(0, n, 50)]
        chunked_content = self._run_chunked(chunks)
        self.assertEqual(chunked_content, self.full_content)

    def test_overlapping_chunks_are_deduplicated_not_miscounted(self):
        # Cas realiste de backfill prudent : chaque nouveau lot re-envoie
        # une petite fenetre de chevauchement (les 20 dernieres bougies du
        # lot precedent) par securite. Doit converger vers EXACTEMENT le
        # meme contenu final, avec les doublons reconnus comme `unchanged`
        # (valeurs identiques) et non comme des collisions ou de nouvelles
        # insertions.
        n = len(ALL_CANDLES)
        size = 400
        overlap = 20
        chunks = []
        start = 0
        while start < n:
            chunks.append(ALL_CANDLES[max(0, start - overlap) : start + size])
            start += size

        existing = {}
        next_id = [0]
        total_inserted = total_collisions = total_unchanged = 0
        for chunk in chunks:
            inserted, collisions, unchanged = _apply(existing, chunk, next_id)
            total_inserted += inserted
            total_collisions += collisions
            total_unchanged += unchanged

        self.assertEqual(total_collisions, 0)  # donnees reelles identiques -> jamais une vraie collision
        self.assertGreater(total_unchanged, 0)  # le chevauchement a bien ete detecte comme redondant
        self.assertEqual(total_inserted, FIXTURE["bars_used"])  # chaque bougie reelle inseree une seule fois

        self.assertEqual(_content(existing), self.full_content)

    def test_single_bar_at_a_time_produces_byte_identical_content(self):
        # Cas extreme : une bougie a la fois (3400 cycles lecture-fusion-
        # ecriture). Le plus proche d'une accumulation live bougie par
        # bougie. Le plus lent mais le plus rigoureux des quatre tests.
        chunks = [[c] for c in ALL_CANDLES]
        chunked_content = self._run_chunked(chunks)
        self.assertEqual(chunked_content, self.full_content)


if __name__ == "__main__":
    unittest.main()
