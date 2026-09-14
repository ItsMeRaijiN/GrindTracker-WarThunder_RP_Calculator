from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from datamine import build_normalized_snapshot
from static_catalog import build_static_catalog
from tests.calculator_contract import CONTRACT_PATH, build_contract


def test_static_ids_survive_reordering_and_catalog_updates():
    source = build_normalized_snapshot(Path(__file__).parent / "fixtures" / "datamine", minimum_vehicles=1)
    before = build_static_catalog(source)
    changed = deepcopy(source)
    changed["vehicles"].reverse()
    after = build_static_catalog(changed)
    assert before["nodes"] == after["nodes"]
    assert before["edges"] == after["edges"]
    ids = {row["id"] for row in before["nodes"]}
    assert all(0 < key < 2**53 for key in ids)
    assert all(row["folder_of"] is None or row["folder_of"] in ids for row in before["nodes"])
    assert all(edge["parent"] in ids and edge["child"] in ids for edge in before["edges"])
    assert before["trees"][0]["research_efficiency"]
    assert set(before) == {"schema_version", "source", "nations", "classes", "nodes", "edges", "trees"}


def test_static_export_rejects_identifier_collisions(monkeypatch):
    source = build_normalized_snapshot(Path(__file__).parent / "fixtures" / "datamine", minimum_vehicles=1)
    monkeypatch.setattr("static_catalog.stable_vehicle_id", lambda _key: 1)
    with pytest.raises(ValueError, match="collided"):
        build_static_catalog(source)


def test_browser_calculator_contract_matches_python():
    assert json.loads(CONTRACT_PATH.read_text(encoding="utf-8")) == build_contract()
