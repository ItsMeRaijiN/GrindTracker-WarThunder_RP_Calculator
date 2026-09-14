from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from calc import rank_efficiency_rules
from catalog import is_temporary_variant
from catalog_view import research_column_count, vehicle_dict
from importer import import_from_json_dict
from models import Base, Nation, Vehicle, VehicleClass, VehicleEdge


def stable_vehicle_id(source_key: str) -> int:
    return int(hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:12], 16) + 1


def export_catalog(session: Session, source: dict[str, Any]) -> dict[str, Any]:
    rows = list(session.scalars(select(Vehicle).order_by(Vehicle.source_key)).unique())
    rows = [
        row for row in rows if row.retired_at is None and not is_temporary_variant(row.source_key, row.availability)
    ]
    if not rows or any(not row.source_key for row in rows):
        raise ValueError("A static catalog requires vehicles with stable source keys.")
    identifiers = {row.id: stable_vehicle_id(str(row.source_key)) for row in rows}
    if len(set(identifiers.values())) != len(rows):
        raise ValueError("Static vehicle identifiers collided; the catalog was not exported.")
    edges = [
        edge
        for edge in session.scalars(select(VehicleEdge))
        if edge.parent_id in identifiers and edge.child_id in identifiers
    ]
    groups: dict[tuple[str, str], list[Vehicle]] = defaultdict(list)
    nodes = []
    for row in rows:
        node = vehicle_dict(row)
        node["id"] = identifiers[row.id]
        node["folder_of"] = identifiers.get(row.folder_of)
        nodes.append(node)
        groups[(row.nation.slug, row.vehicle_class.name)].append(row)
    rules = rank_efficiency_rules()
    trees = []
    for (nation, branch), vehicles in sorted(groups.items()):
        ids = {vehicle.id for vehicle in vehicles}
        tree_edges = [edge for edge in edges if edge.parent_id in ids and edge.child_id in ids]
        trees.append(
            {
                "nation": nation,
                "class": branch,
                "vehicle_count": len(vehicles),
                "research_column_count": research_column_count(vehicles, tree_edges),
                "research_efficiency": rules,
                "source_version": source.get("version"),
                "source_revision": source.get("revision"),
            }
        )
    return {
        "schema_version": 1,
        "source": {key: source.get(key) for key in ("source", "version", "revision", "checksum", "source_url")},
        "nations": [
            {"id": row.id, "slug": row.slug, "name": row.name}
            for row in session.scalars(select(Nation).order_by(Nation.name))
        ],
        "classes": [
            {"id": row.id, "name": row.name}
            for row in session.scalars(select(VehicleClass).order_by(VehicleClass.name))
        ],
        "nodes": nodes,
        "edges": sorted(
            [
                {"parent": identifiers[e.parent_id], "child": identifiers[e.child_id], "unlock_rp": e.unlock_rp}
                for e in edges
            ],
            key=lambda edge: (edge["parent"], edge["child"]),
        ),
        "trees": trees,
    }


def build_static_catalog(data: dict[str, Any]) -> dict[str, Any]:
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            import_from_json_dict(session, data)
            return export_catalog(session, data.get("snapshot", {}))
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a normalized catalog for standalone GitHub Pages hosting")
    parser.add_argument("source", type=Path, help="JSON produced by cli.py sync-datamine --dry-run --export")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    catalog = build_static_catalog(json.loads(args.source.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Exported {len(catalog['nodes'])} vehicles and {len(catalog['trees'])} trees to {args.output}")


if __name__ == "__main__":
    main()
