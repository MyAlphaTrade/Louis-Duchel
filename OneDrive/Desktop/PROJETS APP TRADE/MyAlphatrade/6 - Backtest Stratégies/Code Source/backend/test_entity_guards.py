"""Tests de non-regression -- Research Lab Phase 3, etape 1+2 (2026-09-13).

Couvre l'ajout des types d'entite SyncState/DatasetVersion et la garantie
d'immutabilite d'un DatasetVersion fige (frozen=true) -- voir Phase 2,
decision 8 : "un dataset deja valide ne doit jamais changer silencieusement".

Ne demarre aucun serveur FastAPI (pas de TestClient/httpx) : comme
test_merge_market_data.py, on teste directement la fonction pure extraite
de main.py, dans le meme style que le reste du projet.
"""
import unittest

from main import (
    ENTITY_TYPES,
    IMMUTABLE_WHEN_FROZEN,
    STRATEGY_RULE_FIELDS,
    _check_entity_mutable,
    _check_strategy_rule_fields_mutable,
)
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


class TestActiveStrategyRuleFieldsAreImmutable(unittest.TestCase):
    """Recherche Lab, brique 1/6 (2026-09-15) -- voir Contrat_Execution_
    StrategyLab_Global_2026-09-15.html, decision 4. Corrige le bug reel
    trouve en audit : Strategy.update() reecrivait les regles en place
    meme quand status='active', sans aucune garde."""

    def _active_strategy(self, **overrides):
        base = {
            "name": "Gold Intraday Reversal", "version": "1.0", "status": "active",
            "asset_symbols": ["XAUUSD"], "primary_timeframe": "M15",
            "entry_conditions": {"buy": [], "sell": []},
            "exit_conditions": {"stop_loss": {"type": "pips", "value": 15}},
            "risk_management": {"type": "percent", "risk_value": 1},
        }
        base.update(overrides)
        return base

    def test_rule_field_update_on_active_strategy_is_rejected(self):
        current = self._active_strategy()
        with self.assertRaises(HTTPException) as ctx:
            _check_strategy_rule_fields_mutable(current, {"entry_conditions": {"buy": [{"indicator": "rsi"}], "sell": []}})
        self.assertEqual(ctx.exception.status_code, 409)

    def test_each_rule_field_individually_is_rejected_on_active_strategy(self):
        current = self._active_strategy()
        for field in STRATEGY_RULE_FIELDS:
            with self.assertRaises(HTTPException, msg=f"{field} aurait du etre protege"):
                _check_strategy_rule_fields_mutable(current, {field: "peu importe la valeur"})

    def test_cosmetic_fields_remain_mutable_on_active_strategy(self):
        current = self._active_strategy()
        # Usages reels existants (Strategies.jsx) qui ne doivent pas casser.
        _check_strategy_rule_fields_mutable(current, {"strategy_category": "swing"})
        _check_strategy_rule_fields_mutable(current, {"favorite": True})
        _check_strategy_rule_fields_mutable(current, {"description": "notes mises a jour"})

    def test_status_transition_away_from_active_is_allowed(self):
        current = self._active_strategy()
        _check_strategy_rule_fields_mutable(current, {"status": "archived"})  # ne doit pas lever

    def test_cannot_smuggle_a_rule_change_alongside_a_status_change(self):
        current = self._active_strategy()
        with self.assertRaises(HTTPException):
            _check_strategy_rule_fields_mutable(current, {"status": "draft", "risk_management": {"risk_value": 5}})

    def test_draft_or_tested_strategy_remains_fully_mutable(self):
        for status in ("draft", "tested", "archived"):
            current = self._active_strategy(status=status)
            _check_strategy_rule_fields_mutable(current, {"entry_conditions": {"buy": [], "sell": []}})  # ne doit pas lever

    def test_strategy_without_status_field_defaults_to_mutable(self):
        current = {"name": "brouillon sans statut explicite"}
        _check_strategy_rule_fields_mutable(current, {"entry_conditions": {}})  # ne doit pas lever


if __name__ == "__main__":
    unittest.main()
