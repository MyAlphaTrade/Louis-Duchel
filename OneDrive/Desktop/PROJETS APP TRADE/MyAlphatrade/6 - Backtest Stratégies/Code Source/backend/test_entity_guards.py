"""Tests de non-regression -- Research Lab Phase 3, etape 1+2 (2026-09-13).

Couvre l'ajout des types d'entite SyncState/DatasetVersion et la garantie
d'immutabilite d'un DatasetVersion fige (frozen=true) -- voir Phase 2,
decision 8 : "un dataset deja valide ne doit jamais changer silencieusement".

Ne demarre aucun serveur FastAPI (pas de TestClient/httpx) : comme
test_merge_market_data.py, on teste directement la fonction pure extraite
de main.py, dans le meme style que le reste du projet.
"""
import unittest

from main import ENTITY_TYPES, IMMUTABLE_WHEN_FROZEN, _check_entity_mutable
from fastapi import HTTPException


class TestNewEntityTypesRegistered(unittest.TestCase):
    def test_sync_state_is_a_valid_entity_type(self):
        self.assertIn("SyncState", ENTITY_TYPES)

    def test_dataset_version_is_a_valid_entity_type(self):
        self.assertIn("DatasetVersion", ENTITY_TYPES)

    def test_existing_entity_types_are_untouched(self):
        # Phase 3 ajoute, ne retire et ne renomme jamais un type existant.
        for t in ("TradingAsset", "Strategy", "BacktestResult", "PaperTrade", "Signal", "MarketData"):
            self.assertIn(t, ENTITY_TYPES)


class TestFrozenDatasetVersionIsImmutable(unittest.TestCase):
    def test_dataset_version_is_in_the_immutable_set(self):
        self.assertIn("DatasetVersion", IMMUTABLE_WHEN_FROZEN)

    def test_sync_state_is_never_immutable(self):
        # SyncState n'a pas de notion de "frozen" -- une synchro doit
        # toujours pouvoir progresser.
        self.assertNotIn("SyncState", IMMUTABLE_WHEN_FROZEN)

    def test_frozen_dataset_version_refuses_mutation(self):
        current = {"symbol": "BTCUSD", "window": "3m", "frozen": True}
        with self.assertRaises(HTTPException) as ctx:
            _check_entity_mutable("DatasetVersion", current)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_non_frozen_dataset_version_is_still_mutable(self):
        current = {"symbol": "BTCUSD", "window": "3m", "frozen": False}
        _check_entity_mutable("DatasetVersion", current)  # ne doit pas lever

    def test_dataset_version_without_frozen_field_defaults_to_mutable(self):
        # Coherent avec un DatasetVersion cree avant que frozen ne soit
        # explicitement pose a true -- absence de champ != gele.
        _check_entity_mutable("DatasetVersion", {"symbol": "XAUUSD"})  # ne doit pas lever

    def test_frozen_flag_on_a_non_immutable_entity_type_has_no_effect(self):
        # `frozen` n'a de sens que pour DatasetVersion -- un autre type
        # d'entite qui porterait ce champ par coincidence n'est pas bloque.
        _check_entity_mutable("Strategy", {"frozen": True})  # ne doit pas lever


if __name__ == "__main__":
    unittest.main()
