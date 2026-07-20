from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, overload

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from models import CatalogSnapshot, Nation, Rank, Vehicle, VehicleClass, VehicleEdge


@overload
def _number(value: Any, converter: type[int]) -> int | None: ...


@overload
def _number(value: Any, converter: type[float]) -> float | None: ...


def _number(value: Any, converter: type[int] | type[float]) -> int | float | None:
    if value in (None, ""):
        return None
    try:
        result = converter(value)
        if isinstance(result, float) and not math.isfinite(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


@overload
def _non_negative_number(value: Any, converter: type[int]) -> int | None: ...


@overload
def _non_negative_number(value: Any, converter: type[float]) -> float | None: ...


def _non_negative_number(value: Any, converter: type[int] | type[float]) -> int | float | None:
    result = _number(value, converter)
    return result if result is not None and result >= 0 else None


def _bounded_text(
    value: Any,
    limit: int,
    field: str,
    warnings: list[str],
    *,
    default: str | None = None,
) -> str | None:
    if value in (None, ""):
        return default
    text = str(value).strip()
    if not text:
        return default
    if len(text) <= limit:
        return text
    preview = f"{text[:77]}..." if len(text) > 80 else text
    warnings.append(f"Ignored overlong {field} ({len(text)} > {limit}): {preview!r}")
    return default


def _vehicle_state(vehicle: Vehicle) -> tuple[Any, ...]:
    return (
        vehicle.source_name,
        vehicle.source_version,
        vehicle.name,
        vehicle.nation_id,
        vehicle.class_id,
        vehicle.rank_id,
        vehicle.is_tree,
        vehicle.is_premium,
        vehicle.is_collector,
        vehicle.role,
        vehicle.availability,
        vehicle.research_type,
        vehicle.tree_column,
        vehicle.tree_order,
        vehicle.folder_key,
        vehicle.folder_of,
        vehicle.br_ab,
        vehicle.br_rb,
        vehicle.br_sb,
        vehicle.rp_multiplier,
        vehicle.rp_cost,
        vehicle.sl_cost,
        vehicle.ge_cost,
        vehicle.gjn_cost,
        vehicle.marketplace_item_id,
        vehicle.image_url,
        vehicle.wiki_url,
        vehicle.retired_at,
    )


def _upsert_reference_data(
    session: Session,
    data: dict[str, Any],
    report: dict[str, Any],
) -> tuple[dict[str, Nation], dict[str, VehicleClass], dict[int, Rank]]:
    nations = {item.slug: item for item in session.scalars(select(Nation)).all()}
    for value in data.get("nations", []):
        if not isinstance(value, dict) or not value.get("slug"):
            report["warnings"].append(f"Skipped invalid nation: {value!r}")
            continue
        # noinspection PyUnresolvedReferences
        slug = str(value["slug"]).strip().lower()
        name = str(value.get("name") or slug).strip()
        if len(slug) > 32 or not name or len(name) > 80:
            report["warnings"].append(f"Skipped overlong nation: {slug!r}")
            continue
        nation = nations.get(slug) or Nation(slug=slug, name=slug)
        nation.name = name
        nation.flag_url = _bounded_text(value.get("flag_url"), 500, f"nation {slug} flag_url", report["warnings"])
        session.add(nation)
        nations[slug] = nation
        report["nations"] += 1

    classes = {item.name: item for item in session.scalars(select(VehicleClass)).all()}
    for value in data.get("classes", []):
        name = str(value.get("name") if isinstance(value, dict) else value).strip().lower()
        if not name or len(name) > 32:
            if name:
                report["warnings"].append(f"Skipped overlong vehicle class: {name!r}")
            continue
        item = classes.get(name) or VehicleClass(name=name)
        session.add(item)
        classes[name] = item
        report["classes"] += 1

    ranks = {item.id: item for item in session.scalars(select(Rank)).all()}
    for value in data.get("ranks", []):
        rank_id = _number(value.get("id") if isinstance(value, dict) else None, int)
        if rank_id is None:
            report["warnings"].append(f"Skipped invalid rank: {value!r}")
            continue
        label = str(value.get("label") or rank_id).strip()
        if rank_id <= 0 or not label or len(label) > 16:
            report["warnings"].append(f"Skipped invalid rank: {value!r}")
            continue
        item = ranks.get(rank_id) or Rank(id=rank_id, label=label)
        item.label = label
        session.add(item)
        ranks[rank_id] = item
        report["ranks"] += 1

    session.flush()
    return nations, classes, ranks


def import_from_json_dict(session: Session, data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("The normalized catalog must be a JSON object.")
    snapshot_value = data.get("snapshot")
    snapshot: dict[str, Any] = snapshot_value if isinstance(snapshot_value, dict) else {}
    imported_at = datetime.now(UTC)
    report: dict[str, Any] = {
        "nations": 0,
        "classes": 0,
        "ranks": 0,
        "vehicles": 0,
        "added": 0,
        "updated": 0,
        "unchanged": 0,
        "retired": 0,
        "edges": 0,
        "warnings": [str(value) for value in data.get("warnings", [])]
        if isinstance(data.get("warnings", []), list)
        else ["Ignored invalid top-level warnings value."],
    }
    raw_source_name = snapshot.get("source") or data.get("source")
    source_identity_valid = bool(raw_source_name and len(str(raw_source_name).strip()) <= 80)
    source_name = (
        _bounded_text(
            raw_source_name,
            80,
            "snapshot source",
            report["warnings"],
            default="manual-json",
        )
        or "manual-json"
    )
    source_version = (
        _bounded_text(
            snapshot.get("version") or data.get("source_version"),
            64,
            "snapshot version",
            report["warnings"],
            default="manual",
        )
        or "manual"
    )
    try:
        nations, classes, ranks = _upsert_reference_data(session, data, report)

        key_to_vehicle: dict[str, Vehicle] = {}
        imported_keys: set[str] = set()
        vehicle_states: list[tuple[Vehicle, bool, tuple[Any, ...] | None]] = []
        folder_links: list[tuple[str, str]] = []
        edge_links: list[tuple[str, str, int | None]] = []

        vehicle_values = data.get("vehicles", [])
        if not isinstance(vehicle_values, list):
            raise ValueError("The normalized catalog 'vehicles' field must be a list.")
        candidate_keys = {
            str(value.get("key") or value.get("id") or value.get("name") or "").strip()
            for value in vehicle_values
            if isinstance(value, dict)
        }
        existing_vehicles = (
            {
                vehicle.source_key: vehicle
                for vehicle in session.scalars(select(Vehicle).where(Vehicle.source_key.in_(candidate_keys))).all()
                if vehicle.source_key
            }
            if candidate_keys
            else {}
        )
        for value in vehicle_values:
            if not isinstance(value, dict):
                report["warnings"].append(f"Skipped invalid vehicle: {value!r}")
                continue
            key = str(value.get("key") or value.get("id") or value.get("name") or "").strip()
            name = str(value.get("name") or "").strip()
            if key in imported_keys:
                raise ValueError(f"Duplicate vehicle key in normalized catalog: {key!r}")
            if len(key) > 160 or len(name) > 160:
                report["warnings"].append(f"Skipped overlong vehicle: {key or name!r}")
                continue
            nation = nations.get(str(value.get("nation") or "").lower())
            vehicle_class = classes.get(str(value.get("class") or "").lower())
            rank_id = int(_number(value.get("rank"), int) or 0)
            if not key or not name or nation is None or vehicle_class is None or rank_id <= 0:
                report["warnings"].append(f"Skipped incomplete vehicle: {key or value!r}")
                continue
            rank = ranks.get(rank_id)
            if rank is None:
                rank = Rank(id=rank_id, label=str(rank_id))
                session.add(rank)
                ranks[rank_id] = rank
                report["ranks"] += 1

            vehicle = existing_vehicles.get(key)
            is_new = vehicle is None
            if vehicle is None:
                vehicle = Vehicle(name=name, nation_id=nation.id, class_id=vehicle_class.id, rank_id=rank.id)
            previous = None if is_new else _vehicle_state(vehicle)

            vehicle.source_key = key
            vehicle.source_name = _bounded_text(
                value.get("source"),
                80,
                f"vehicle {key} source",
                report["warnings"],
                default=source_name,
            )
            vehicle.source_version = _bounded_text(
                value.get("source_version"),
                64,
                f"vehicle {key} source_version",
                report["warnings"],
                default=source_version,
            )
            vehicle.name = name
            vehicle.nation_id = nation.id
            vehicle.class_id = vehicle_class.id
            vehicle.rank_id = rank.id
            kind = str(value.get("type") or "tree").strip().lower()
            if kind not in {"tree", "premium", "collector", "squadron"}:
                report["warnings"].append(f"Vehicle {key} has an unknown type {kind!r}; using collector.")
                kind = "collector"
            vehicle.is_tree = kind == "tree"
            vehicle.is_premium = kind == "premium"
            vehicle.is_collector = kind in {"collector", "squadron"}
            vehicle.role = _bounded_text(value.get("role"), 64, f"vehicle {key} role", report["warnings"])
            default_availability = "researchable" if kind == "tree" else kind
            vehicle.availability = (
                _bounded_text(
                    value.get("availability"),
                    32,
                    f"vehicle {key} availability",
                    report["warnings"],
                    default=default_availability,
                )
                or default_availability
            )
            default_research_type = "standard" if kind == "tree" else kind
            vehicle.research_type = (
                _bounded_text(
                    value.get("research_type"),
                    32,
                    f"vehicle {key} research_type",
                    report["warnings"],
                    default=default_research_type,
                )
                or default_research_type
            )
            vehicle.tree_column = _non_negative_number(value.get("tree_column"), int)
            vehicle.tree_order = _non_negative_number(value.get("tree_order"), int)
            vehicle.folder_key = _bounded_text(
                value.get("folder_key"),
                160,
                f"vehicle {key} folder_key",
                report["warnings"],
            )
            vehicle.folder_of = None
            vehicle.rp_cost = _non_negative_number(value.get("rp_cost"), int)
            vehicle.sl_cost = _non_negative_number(value.get("sl_cost"), int)
            vehicle.ge_cost = _non_negative_number(value.get("ge_cost"), int)
            vehicle.gjn_cost = _non_negative_number(value.get("gjn_cost"), float)
            vehicle.marketplace_item_id = _non_negative_number(value.get("marketplace_item_id"), int)
            br_value = value.get("br")
            br: dict[str, Any] = br_value if isinstance(br_value, dict) else {}
            vehicle.br_ab = _non_negative_number(value.get("br_ab", br.get("ab")), float)
            vehicle.br_rb = _non_negative_number(value.get("br_rb", br.get("rb")), float)
            vehicle.br_sb = _non_negative_number(value.get("br_sb", br.get("sb")), float)
            vehicle.rp_multiplier = _non_negative_number(value.get("rp_multiplier"), float)
            vehicle.image_url = _bounded_text(
                value.get("image_url"),
                500,
                f"vehicle {key} image_url",
                report["warnings"],
            )
            vehicle.wiki_url = _bounded_text(
                value.get("wiki_url"),
                500,
                f"vehicle {key} wiki_url",
                report["warnings"],
            )
            vehicle.retired_at = None
            session.add(vehicle)

            imported_keys.add(key)
            key_to_vehicle[key] = vehicle
            vehicle_states.append((vehicle, is_new, previous))
            report["vehicles"] += 1

            folder_key = _bounded_text(
                value.get("folder_of_key"),
                160,
                f"vehicle {key} folder_of_key",
                report["warnings"],
            )
            if folder_key:
                folder_links.append((key, folder_key))
            embedded_value = value.get("edges")
            embedded: dict[str, Any] = embedded_value if isinstance(embedded_value, dict) else {}
            unlock_rp = _non_negative_number(embedded.get("unlock_rp"), int)
            for parent in embedded.get("parents") or []:
                parent_key = _bounded_text(
                    parent,
                    160,
                    f"vehicle {key} edge parent",
                    report["warnings"],
                )
                if parent_key:
                    edge_links.append((parent_key, key, unlock_rp))

        session.flush()

        retire_missing = snapshot.get("retire_missing")
        if retire_missing is True and not source_identity_valid:
            report["warnings"].append("Ignored retire_missing because the snapshot source is missing or invalid.")
            retire_missing = False

        retired_ids: list[int] = []
        if isinstance(retire_missing, bool) and retire_missing:
            if not imported_keys:
                raise ValueError("Refusing to retire a catalog source from an empty or invalid snapshot.")
            existing = session.scalars(select(Vehicle).filter_by(source_name=source_name)).all()
            for vehicle in existing:
                already_imported = vehicle.source_key and vehicle.source_key in imported_keys
                if not already_imported and vehicle.retired_at is None:
                    vehicle.is_tree = False
                    vehicle.is_premium = False
                    vehicle.is_collector = True
                    vehicle.availability = "retired"
                    vehicle.research_type = "unavailable"
                    vehicle.retired_at = imported_at
                    retired_ids.append(vehicle.id)
                    report["retired"] += 1

        if retired_ids:
            session.execute(
                delete(VehicleEdge).where(
                    or_(VehicleEdge.parent_id.in_(retired_ids), VehicleEdge.child_id.in_(retired_ids)),
                    VehicleEdge.source_name == source_name,
                )
            )

        imported_ids = [vehicle.id for vehicle in key_to_vehicle.values()]
        if imported_ids:
            session.execute(
                delete(VehicleEdge).where(
                    VehicleEdge.child_id.in_(imported_ids),
                    VehicleEdge.source_name == source_name,
                )
            )

        for child_key, parent_key in folder_links:
            child = key_to_vehicle.get(child_key)
            parent = key_to_vehicle.get(parent_key)
            if child and parent:
                child.folder_of = parent.id
            else:
                report["warnings"].append(f"Unresolved folder: {child_key} -> {parent_key}")

        for vehicle, is_new, previous in vehicle_states:
            if is_new:
                report["added"] += 1
            elif previous == _vehicle_state(vehicle):
                report["unchanged"] += 1
            else:
                report["updated"] += 1

        for value in data.get("edges", []):
            if isinstance(value, dict):
                parent_key = _bounded_text(value.get("parent_key"), 160, "edge parent_key", report["warnings"])
                child_key = _bounded_text(value.get("child_key"), 160, "edge child_key", report["warnings"])
                if parent_key and child_key:
                    edge_links.append((parent_key, child_key, _non_negative_number(value.get("unlock_rp"), int)))

        unique_edges: dict[tuple[str, str], int | None] = {}
        for parent_key, child_key, unlock_rp in edge_links:
            unique_edges.setdefault((parent_key, child_key), unlock_rp)

        existing_edges = (
            {
                (edge.parent_id, edge.child_id): edge
                for edge in session.scalars(select(VehicleEdge).where(VehicleEdge.child_id.in_(imported_ids))).all()
            }
            if imported_ids
            else {}
        )

        for (parent_key, child_key), unlock_rp in unique_edges.items():
            parent = key_to_vehicle.get(parent_key)
            child = key_to_vehicle.get(child_key)
            if not parent or not child or parent.id == child.id:
                report["warnings"].append(f"Unresolved edge: {parent_key} -> {child_key}")
                continue
            existing_edge = existing_edges.get((parent.id, child.id))
            if existing_edge is None:
                session.add(
                    VehicleEdge(
                        parent_id=parent.id,
                        child_id=child.id,
                        unlock_rp=unlock_rp,
                        source_name=source_name,
                    )
                )
                report["edges"] += 1
            else:
                comparison = (
                    "matching unlock_rp"
                    if existing_edge.unlock_rp == unlock_rp
                    else f"unlock_rp {existing_edge.unlock_rp!r}; snapshot requested {unlock_rp!r}"
                )
                report["warnings"].append(f"Preserved non-importer edge {parent_key} -> {child_key} with {comparison}.")

        if snapshot:
            revision = (
                _bounded_text(
                    snapshot.get("revision"),
                    64,
                    "snapshot revision",
                    report["warnings"],
                    default=source_version,
                )
                or source_version
            )
            checksum = (
                _bounded_text(
                    snapshot.get("checksum"),
                    64,
                    "snapshot checksum",
                    report["warnings"],
                    default="unknown",
                )
                or "unknown"
            )
            record = session.scalar(
                select(CatalogSnapshot).where(
                    CatalogSnapshot.source == source_name,
                    CatalogSnapshot.revision == revision,
                )
            )
            session.execute(
                update(CatalogSnapshot).where(CatalogSnapshot.source == source_name).values(is_active=False)
            )
            if record is None:
                record = CatalogSnapshot(
                    source=source_name,
                    version=source_version,
                    revision=revision,
                    checksum=checksum,
                    vehicle_count=report["vehicles"],
                )
            record.version = source_version
            record.checksum = checksum
            record.source_url = _bounded_text(
                snapshot.get("source_url"),
                500,
                "snapshot source_url",
                report["warnings"],
            )
            record.imported_at = imported_at
            record.vehicle_count = report["vehicles"]
            record.warning_count = len(report["warnings"])
            record.is_active = True
            session.add(record)

        session.commit()
        return report
    except Exception:
        session.rollback()
        raise


def import_from_json_file(session: Session, path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return import_from_json_dict(session, json.load(handle))
