from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from calc import Forecast, estimate_cascade, estimate_vehicle, summarize_recent_battles
from importer import import_from_json_dict
from models import Base, Vehicle
from schemas import CalcPayload
from static_catalog import export_catalog, stable_vehicle_id

CONTRACT_PATH = Path(__file__).parent / "fixtures" / "calculator-contract.json"


def build_contract() -> dict[str, Any]:
    vehicles = [
        {"key": "reserve", "rank": 1, "rp_cost": None, "rp_multiplier": 1},
        {"key": "regular", "rank": 3, "rp_cost": 12000, "rp_multiplier": 1.7},
        {"key": "premium", "rank": 3, "type": "premium", "rp_cost": None, "rp_multiplier": 2.4},
        {"key": "folder", "rank": 4, "rp_cost": 2600, "rp_multiplier": 1.4},
        {"key": "target", "rank": 4, "rp_cost": 5900, "rp_multiplier": 1.4, "folder_of_key": "folder"},
        {"key": "high", "rank": 7, "rp_cost": 80000, "rp_multiplier": 2.2},
        {"key": "low", "rank": 1, "rp_cost": 6000, "rp_multiplier": 1.1},
    ]
    for order, vehicle in enumerate(vehicles):
        vehicle.update(
            name=str(vehicle["key"]).title(), nation="usa", **{"class": "army"}, tree_column=0, tree_order=order
        )
    data = {
        "snapshot": {"source": "calculator-contract", "version": "1", "revision": "contract-v1"},
        "nations": [{"slug": "usa", "name": "USA"}],
        "classes": ["army"],
        "vehicles": vehicles,
        "edges": [
            {"parent": "reserve", "child": "regular"},
            {"parent": "reserve", "child": "folder"},
            {"parent": "regular", "child": "target"},
            {"parent": "target", "child": "high"},
        ],
    }
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            import_from_json_dict(session, data)
            rows = {v.source_key: v for v in session.scalars(select(Vehicle))}
            ids = {v.id: stable_vehicle_id(str(v.source_key)) for v in rows.values()}

            def transform(value: Any, field: str = "") -> Any:
                if isinstance(value, dict):
                    return {key: transform(item, key) for key, item in value.items()}
                if field in {"required_ids", "prerequisite_ids"}:
                    mapped = [ids[item] for item in value]
                    return sorted(mapped[:-1]) + mapped[-1:] if field == "required_ids" else sorted(mapped)
                if isinstance(value, list):
                    mapped = [transform(item) for item in value]
                    return sorted(mapped, key=lambda row: row["id"]) if field == "prerequisites" else mapped
                return ids[value] if field == "id" else value

            scenarios: list[tuple[str, str, str, str | None, dict[str, Any]]] = [
                ("observed predecessor", "estimate", "target", "regular", {"avg_rp_per_battle": 2100}),
                ("arcade predecessor", "estimate", "target", "regular", {"avg_rp_per_battle": 2100, "game_mode": "ab"}),
                (
                    "simulator predecessor",
                    "estimate",
                    "target",
                    "regular",
                    {"avg_rp_per_battle": 2100, "game_mode": "sb"},
                ),
                (
                    "additive base bonuses",
                    "estimate",
                    "target",
                    "regular",
                    {
                        "avg_rp_per_battle": 1234,
                        "rp_is_base": True,
                        "has_premium": True,
                        "has_talisman": True,
                        "booster_percent": 150,
                        "skill_bonus_percent": 75,
                    },
                ),
                (
                    "observed bonuses not applied twice",
                    "estimate",
                    "high",
                    "premium",
                    {
                        "avg_rp_per_battle": 2000,
                        "has_premium": True,
                        "booster_percent": 100,
                    },
                ),
                ("premium lower rank", "estimate", "low", "premium", {"avg_rp_per_battle": 2500}),
                ("premium upper efficient rank", "estimate", "target", "premium", {"avg_rp_per_battle": 2500}),
                ("regular lower rank", "estimate", "low", "regular", {"avg_rp_per_battle": 2500}),
                ("regular far higher rank", "estimate", "high", "regular", {"avg_rp_per_battle": 2500}),
                (
                    "recent battle average",
                    "estimate",
                    "target",
                    "regular",
                    {
                        "avg_rp_per_battle": 9999,
                        "avg_battle_minutes": 99,
                        "recent_battles": [
                            {"rp": 2000, "minutes": 7.5},
                            {"rp": 1750, "minutes": 0},
                            {"rp": 0, "minutes": 12},
                        ],
                    },
                ),
                ("unknown pace", "estimate", "target", None, {}),
                ("completed target", "estimate", "target", None, {"rp_current": 9000}),
                (
                    "half-minute rounding",
                    "estimate",
                    "target",
                    None,
                    {"avg_rp_per_battle": 10000, "avg_battle_minutes": 2.5},
                ),
                ("fractional RP rounding", "estimate", "target", None, {"avg_rp_per_battle": 2.675}),
                ("decimal tie to even", "estimate", "target", None, {"avg_rp_per_battle": 1.125}),
                ("shared and folder prerequisites", "cascade", "high", "regular", {"avg_rp_per_battle": 2100}),
                ("cascade unknown pace", "cascade", "high", "regular", {}),
                (
                    "cascade manual target progress",
                    "cascade",
                    "target",
                    "regular",
                    {
                        "avg_rp_per_battle": 2000,
                        "rp_current": 4000,
                        "progress": {rows["regular"].id: {"rp_current": 12000, "done": True}},
                    },
                ),
                (
                    "cascade explicitly completed route",
                    "cascade",
                    "target",
                    "regular",
                    {
                        "progress": {row.id: {"rp_current": 0, "done": True} for row in rows.values()},
                    },
                ),
            ]
            cases = []
            for name, kind, target_key, source_key, values in scenarios:
                target = rows[target_key]
                source = rows[source_key] if source_key else None
                payload = CalcPayload(vehicle_id=target.id, research_vehicle_id=source.id if source else None, **values)
                rp, minutes, samples = summarize_recent_battles([row.model_dump() for row in payload.recent_battles])
                pace = Forecast(
                    avg_rp_per_battle=rp if samples else payload.avg_rp_per_battle,
                    avg_battle_minutes=minutes if samples else payload.avg_battle_minutes,
                    rp_is_base=payload.rp_is_base,
                    has_premium=payload.has_premium,
                    booster_percent=payload.booster_percent,
                    skill_bonus_percent=payload.skill_bonus_percent,
                    has_talisman=payload.has_talisman,
                    game_mode=payload.game_mode,
                )
                if kind == "estimate":
                    expected = estimate_vehicle(session, target, payload.rp_current, pace, samples, source)
                else:
                    progress = {key: (value.rp_current, value.done) for key, value in payload.progress.items()}
                    progress.setdefault(target.id, (payload.rp_current, False))
                    expected = estimate_cascade(session, target, progress, pace, samples, source)
                web_payload = payload.model_dump(exclude_none=True)
                web_payload["vehicle_id"] = ids[target.id]
                if source:
                    web_payload["research_vehicle_id"] = ids[source.id]
                web_payload["progress"] = {str(ids[key]): value for key, value in web_payload["progress"].items()}
                cases.append({"name": name, "kind": kind, "payload": web_payload, "expected": transform(expected)})
            return {"catalog": export_catalog(session, data["snapshot"]), "cases": cases}
    finally:
        engine.dispose()


if __name__ == "__main__":
    CONTRACT_PATH.write_text(json.dumps(build_contract(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
