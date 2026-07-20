from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import func, select

from catalog import is_temporary_variant
from database import SessionLocal
from datamine import DatamineValidationError, _availability, _direct_ge_cost, build_normalized_snapshot
from importer import import_from_json_dict
from models import CatalogSnapshot, Rank, Vehicle, VehicleEdge

FIXTURE = Path(__file__).parent / "fixtures" / "datamine"


def test_datamine_adapter_preserves_layout_folders_and_dependencies():
    data = build_normalized_snapshot(FIXTURE, minimum_vehicles=1)
    vehicles = {item["key"]: item for item in data["vehicles"]}

    assert data["snapshot"]["version"] == "2.57.1.19"
    assert data["validation"]["vehicle_count"] == 4
    assert vehicles["us_m3_stuart"]["tree_column"] == 0
    assert vehicles["us_m3a1_stuart"]["tree_order"] == 2
    assert vehicles["us_m3a1_stuart"]["folder_of_key"] == "us_m3_stuart"
    assert vehicles["us_m3_stuart"]["br"]["rb"] == 2.0
    assert vehicles["us_m3_stuart"]["rp_multiplier"] == 1.25
    assert vehicles["us_m901_itv"]["availability"] == "squadron"
    assert {tuple(edge.values()) for edge in data["edges"]} >= {
        ("us_m2a4", "us_m3_stuart"),
        ("us_m3_stuart", "us_m3a1_stuart"),
    }


def test_vehicle_type_and_acquisition_channel_are_classified_separately():
    battle_pass = {
        "gift": "msi_notebook",
        "event": "battlepass_season10",
        "marketplaceItemdefId": 50210,
        "costGold": 8200,
    }
    assert _availability(battle_pass) == ("premium", "battle_pass", "event_only")
    assert _direct_ge_cost(battle_pass, "battle_pass") is None

    store_pack = {"gift": "store_pack", "costGold": 6090}
    assert _availability(store_pack) == ("premium", "pack", "pack")
    assert _direct_ge_cost(store_pack, "pack") is None

    event_reward = {"gift": "msi_notebook", "event": "winter_2025"}
    assert _availability(event_reward) == ("collector", "event", "event_only")
    assert _direct_ge_cost(event_reward, "event") is None


@pytest.mark.parametrize(
    "source_key",
    [
        "germ_a7v_event",
        "ussr_t_80u_race",
        "ah_64a_killstreak",
        "nt_f_4e",
    ],
)
def test_temporary_mode_variant_keys_are_identified(source_key):
    assert is_temporary_variant(source_key)


@pytest.mark.parametrize(
    ("source_key", "availability"),
    [
        ("germ_a7v", None),
        ("bf-109c_1_promo", "special"),
        ("us_winter_reward_event", "event"),
        (None, None),
    ],
)
def test_persistent_catalog_vehicle_keys_are_not_treated_as_temporary(source_key, availability):
    assert not is_temporary_variant(source_key, availability)


def test_datamine_excludes_mode_copies_but_keeps_real_event_rewards(tmp_path):
    source = tmp_path / "temporary-variants"
    shutil.copytree(FIXTURE, source)
    shop_path = source / "char.vromfs.bin_u" / "config" / "shop.blkx"
    economy_path = source / "char.vromfs.bin_u" / "config" / "wpcost.blkx"
    shop = json.loads(shop_path.read_text(encoding="utf-8"))
    economy = json.loads(economy_path.read_text(encoding="utf-8"))
    special_column = shop["country_usa"]["army"]["range"][1]
    temporary_keys = {
        "us_tank_event",
        "us_tank_race",
        "us_tank_killstreak",
        "nt_us_tank",
    }
    for source_key in temporary_keys:
        special_column[source_key] = {"rank": 2, "showOnlyWhenBought": True}
        economy[source_key] = {"rank": 2, "reqExp": 2_900}
    special_column["us_winter_reward_event"] = {"rank": 2, "event": "winter_2026"}
    economy["us_winter_reward_event"] = {"rank": 2, "reqExp": 2_900}
    shop_path.write_text(json.dumps(shop), encoding="utf-8")
    economy_path.write_text(json.dumps(economy), encoding="utf-8")

    data = build_normalized_snapshot(source, minimum_vehicles=1)
    vehicles = {item["key"]: item for item in data["vehicles"]}

    assert temporary_keys.isdisjoint(vehicles)
    assert vehicles["us_winter_reward_event"]["availability"] == "event"
    assert data["validation"]["temporary_variants"] == len(temporary_keys)


def test_only_direct_ge_offers_expose_the_nominal_gold_cost():
    direct = {"costGold": 6090}
    assert _availability(direct) == ("premium", "premium", "premium")
    assert _direct_ge_cost(direct, "premium") == 6090

    limited = {"costGold": 1300, "showOnlyWhenAvailableForPurchase": True}
    assert _availability(limited) == ("premium", "limited", "limited")
    assert _direct_ge_cost(limited, "limited") == 1300

    squadron = {"costGold": 7000, "isClanVehicle": True}
    assert _availability(squadron) == ("collector", "squadron", "squadron_rp")
    assert _direct_ge_cost(squadron, "squadron") is None


def test_battle_pass_marketplace_marker_survives_normalization(tmp_path):
    source = tmp_path / "battle-pass"
    shutil.copytree(FIXTURE, source)
    shop_path = source / "char.vromfs.bin_u" / "config" / "shop.blkx"
    economy_path = source / "char.vromfs.bin_u" / "config" / "wpcost.blkx"
    shop = json.loads(shop_path.read_text(encoding="utf-8"))
    economy = json.loads(economy_path.read_text(encoding="utf-8"))
    shop["country_usa"]["army"]["range"][1]["us_battle_pass_tank"] = {
        "rank": 5,
        "gift": "msi_notebook",
        "event": "battlepass_season10",
        "marketplaceItemdefId": 50210,
    }
    economy["us_battle_pass_tank"] = {
        "rank": 5,
        "costGold": 8200,
        "expMul": 1.96,
    }
    shop_path.write_text(json.dumps(shop), encoding="utf-8")
    economy_path.write_text(json.dumps(economy), encoding="utf-8")

    data = build_normalized_snapshot(source, minimum_vehicles=1)
    vehicle = next(item for item in data["vehicles"] if item["key"] == "us_battle_pass_tank")

    assert vehicle["type"] == "premium"
    assert vehicle["availability"] == "battle_pass"
    assert vehicle["ge_cost"] is None
    assert vehicle["marketplace_item_id"] == 50210


def test_datamine_rejects_invalid_revision_and_missing_english_column(tmp_path):
    invalid_revision = tmp_path / "invalid-revision"
    shutil.copytree(FIXTURE, invalid_revision)
    (invalid_revision / ".grindtracker-revision").write_text("master", encoding="ascii")
    with pytest.raises(DatamineValidationError, match="40-character Git SHA"):
        build_normalized_snapshot(invalid_revision, minimum_vehicles=1)

    missing_english = tmp_path / "missing-english"
    shutil.copytree(FIXTURE, missing_english)
    units = missing_english / "lang.vromfs.bin_u" / "lang" / "units.csv"
    units.write_text("<ID|readonly|noverify>;<Polish>\nus_m2a4_shop;M2A4\n", encoding="utf-8")
    with pytest.raises(DatamineValidationError, match="<English>"):
        build_normalized_snapshot(missing_english, minimum_vehicles=1)


def test_shop_metadata_is_not_reported_as_an_unknown_nation(tmp_path):
    source = tmp_path / "shop-metadata"
    shutil.copytree(FIXTURE, source)
    shop_path = source / "char.vromfs.bin_u" / "config" / "shop.blkx"
    shop = json.loads(shop_path.read_text(encoding="utf-8"))
    shop["metadata"] = {"generated": True}
    shop["country_future"] = {}
    shop_path.write_text(json.dumps(shop), encoding="utf-8")

    data = build_normalized_snapshot(source, minimum_vehicles=1)

    assert data["validation"]["unknown_nations"] == 1


def test_datamine_sync_does_not_hijack_or_retire_manual_rows(client):
    with SessionLocal() as session:
        legacy = Vehicle(
            name="Demo Tank (Premium)",
            nation_id=session.scalar(select(Vehicle.nation_id).limit(1)),
            class_id=session.scalar(select(Vehicle.class_id).limit(1)),
            rank_id=session.scalar(select(Vehicle.rank_id).limit(1)),
            is_tree=True,
        )
        session.add(legacy)
        session.commit()
        import_from_json_dict(session, build_normalized_snapshot(FIXTURE, minimum_vehicles=1))
        session.refresh(legacy)
        assert legacy.availability == "researchable"
        assert legacy.is_tree is True
        assert legacy.retired_at is None


def test_tree_hides_legacy_mode_copies_without_hiding_event_rewards(client):
    with SessionLocal() as session:
        template = session.scalar(select(Vehicle).where(Vehicle.source_key == "us_m3_stuart"))
        assert template is not None
        common = {
            "source_name": "war-thunder-datamine",
            "source_version": template.source_version,
            "nation_id": template.nation_id,
            "class_id": template.class_id,
            "rank_id": template.rank_id,
            "is_tree": False,
            "is_collector": True,
            "rp_cost": 2_900,
        }
        session.add_all(
            [
                Vehicle(
                    source_key="us_m3_stuart_event",
                    name="Temporary Stuart copy",
                    availability="unavailable",
                    research_type="unavailable",
                    **common,
                ),
                Vehicle(
                    source_key="us_winter_reward_event",
                    name="Persistent event reward",
                    availability="event",
                    research_type="event_only",
                    **common,
                ),
            ]
        )
        session.commit()

    response = client.get("/api/tree", params={"nation": "usa", "class": "army"})
    names = {vehicle["name"] for vehicle in response.json()["nodes"]}

    assert response.status_code == 200
    assert "Temporary Stuart copy" not in names
    assert "Persistent event reward" in names


def test_datamine_sync_retires_only_missing_rows_from_the_same_source(client):
    with SessionLocal() as session:
        existing = session.scalar(select(Vehicle).where(Vehicle.source_name == "war-thunder-datamine"))
        assert existing is not None
        missing = Vehicle(
            source_key="removed_datamine_vehicle",
            source_name="war-thunder-datamine",
            source_version="old",
            name="Removed datamine vehicle",
            nation_id=session.scalar(select(Vehicle.nation_id).limit(1)),
            class_id=session.scalar(select(Vehicle.class_id).limit(1)),
            rank_id=session.scalar(select(Vehicle.rank_id).limit(1)),
            is_tree=True,
        )
        session.add(missing)
        session.flush()
        session.add(
            VehicleEdge(
                parent_id=existing.id,
                child_id=missing.id,
                source_name="war-thunder-datamine",
            )
        )
        session.add(
            VehicleEdge(
                parent_id=missing.id,
                child_id=existing.id,
                source_name="war-thunder-datamine",
            )
        )
        session.commit()
        import_from_json_dict(session, build_normalized_snapshot(FIXTURE, minimum_vehicles=1))
        session.refresh(missing)
        assert missing.availability == "retired"
        assert missing.retired_at is not None
        stale_edges = session.scalar(
            select(func.count())
            .select_from(VehicleEdge)
            .where((VehicleEdge.parent_id == missing.id) | (VehicleEdge.child_id == missing.id))
        )
        assert stale_edges == 0

    response = client.get("/api/tree", params={"nation": "usa", "class": "army"})
    assert response.status_code == 200
    assert all(vehicle["name"] != "Removed datamine vehicle" for vehicle in response.json()["nodes"])


def test_datamine_resync_preserves_manual_edges(client):
    data = build_normalized_snapshot(FIXTURE, minimum_vehicles=1)
    desired = data["edges"][0]
    with SessionLocal() as session:
        parent = session.scalar(select(Vehicle).where(Vehicle.source_key == desired["parent_key"]))
        child = session.scalar(select(Vehicle).where(Vehicle.source_key == desired["child_key"]))
        assert parent is not None and child is not None
        existing = session.scalar(
            select(VehicleEdge).where(
                VehicleEdge.parent_id == parent.id,
                VehicleEdge.child_id == child.id,
            )
        )
        assert existing is not None
        session.delete(existing)
        session.flush()
        manual = VehicleEdge(parent_id=parent.id, child_id=child.id, unlock_rp=777)
        session.add(manual)
        session.commit()
        manual_id = manual.id

        report = import_from_json_dict(session, data)

        preserved = session.get(VehicleEdge, manual_id)
        managed_edges = session.scalar(
            select(func.count()).select_from(VehicleEdge).where(VehicleEdge.source_name == "war-thunder-datamine")
        )
        assert preserved is not None
        assert preserved.source_name is None
        assert preserved.unlock_rp == 777
        assert report["edges"] == managed_edges
        assert any("Preserved non-importer edge" in warning for warning in report["warnings"])


def test_importer_does_not_create_ranks_for_rejected_vehicles(client):
    data = build_normalized_snapshot(FIXTURE, minimum_vehicles=1)
    data["vehicles"].append(
        {
            **data["vehicles"][0],
            "key": "rejected-rank-source",
            "name": "Rejected rank source",
            "nation": "missing-nation",
            "rank": 99,
        }
    )

    with SessionLocal() as session:
        import_from_json_dict(session, data)
        assert session.get(Rank, 99) is None


def test_duplicate_edges_with_conflicting_unlock_rp_import_once(client):
    data = build_normalized_snapshot(FIXTURE, minimum_vehicles=1)
    duplicated = next(iter(data["edges"]))
    data["edges"].append({**duplicated, "unlock_rp": 999})
    for vehicle in data["vehicles"]:
        if vehicle["key"] == duplicated["child_key"]:
            vehicle["edges"] = {"parents": [duplicated["parent_key"]], "unlock_rp": 123}
    with SessionLocal() as session:
        report = import_from_json_dict(session, data)
        edge_count = session.scalar(
            select(func.count())
            .select_from(VehicleEdge)
            .join(Vehicle, Vehicle.id == VehicleEdge.child_id)
            .where(Vehicle.source_name == "war-thunder-datamine")
        )
    assert report["edges"] == 2
    assert edge_count == 2


def test_datamine_publish_is_idempotent(client):
    data = build_normalized_snapshot(FIXTURE, minimum_vehicles=1)
    with SessionLocal() as session:
        first = import_from_json_dict(session, data)
        second = import_from_json_dict(session, data)
        source_count = session.scalar(
            select(func.count()).select_from(Vehicle).where(Vehicle.source_name == "war-thunder-datamine")
        )
        snapshot_count = session.scalar(select(func.count()).select_from(CatalogSnapshot))
        edge_count = session.scalar(
            select(func.count())
            .select_from(VehicleEdge)
            .join(Vehicle, Vehicle.id == VehicleEdge.child_id)
            .where(Vehicle.source_name == "war-thunder-datamine")
        )

    assert first["vehicles"] == 4
    assert second["added"] == 0
    assert second["unchanged"] == 4
    assert source_count == 4
    assert snapshot_count == 1
    assert edge_count == 2


def test_import_rejects_duplicate_keys_and_empty_retiring_snapshot(client):
    duplicate = build_normalized_snapshot(FIXTURE, minimum_vehicles=1)
    duplicate["vehicles"].append(dict(duplicate["vehicles"][0]))
    with SessionLocal() as session, pytest.raises(ValueError, match="Duplicate vehicle key"):
        import_from_json_dict(session, duplicate)

    empty = build_normalized_snapshot(FIXTURE, minimum_vehicles=1)
    empty["vehicles"] = []
    empty["edges"] = []
    with SessionLocal() as session, pytest.raises(ValueError, match="Refusing to retire"):
        import_from_json_dict(session, empty)


def test_import_discards_negative_economy_values(client):
    data = build_normalized_snapshot(FIXTURE, minimum_vehicles=1)
    key = data["vehicles"][0]["key"]
    data["vehicles"][0].update(
        {
            "tree_column": -1,
            "tree_order": -2,
            "rp_cost": -3,
            "sl_cost": -4,
            "ge_cost": -5,
            "gjn_cost": -6,
            "br": {"ab": -1, "rb": -1, "sb": -1},
            "rp_multiplier": -1,
        }
    )
    with SessionLocal() as session:
        import_from_json_dict(session, data)
        vehicle = session.scalar(select(Vehicle).where(Vehicle.source_key == key))
        assert vehicle is not None
        assert vehicle.tree_column is None
        assert vehicle.tree_order is None
        assert vehicle.rp_cost is None
        assert vehicle.sl_cost is None
        assert vehicle.ge_cost is None
        assert vehicle.gjn_cost is None
        assert vehicle.br_ab is None
        assert vehicle.br_rb is None
        assert vehicle.br_sb is None
        assert vehicle.rp_multiplier is None


def test_importer_reports_and_discards_every_overlong_text_field(client):
    data = build_normalized_snapshot(FIXTURE, minimum_vehicles=1)
    huge = "x" * 600
    key = data["vehicles"][0]["key"]
    data["nations"][0]["flag_url"] = huge
    data["snapshot"]["source_url"] = huge
    data["vehicles"][0].update(
        {
            "source": huge,
            "source_version": huge,
            "role": huge,
            "availability": huge,
            "research_type": huge,
            "folder_key": huge,
            "image_url": huge,
            "wiki_url": huge,
        }
    )

    with SessionLocal() as session:
        report = import_from_json_dict(session, data)
        vehicle = session.scalar(select(Vehicle).where(Vehicle.source_key == key))
        snapshot = session.scalar(select(CatalogSnapshot).where(CatalogSnapshot.is_active.is_(True)))

    assert vehicle is not None
    assert vehicle.source_name == "war-thunder-datamine"
    assert vehicle.source_version == data["snapshot"]["version"]
    assert vehicle.role is None
    assert vehicle.availability == "researchable"
    assert vehicle.research_type == "standard"
    assert vehicle.folder_key is None
    assert vehicle.image_url is None
    assert vehicle.wiki_url is None
    assert snapshot is not None and snapshot.source_url is None
    assert len(report["warnings"]) >= 10
    assert all("overlong" in warning for warning in report["warnings"])
