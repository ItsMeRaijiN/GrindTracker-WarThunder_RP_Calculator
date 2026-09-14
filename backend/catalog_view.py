from __future__ import annotations

from typing import Any

from models import Vehicle, VehicleEdge


def vehicle_dict(vehicle: Vehicle) -> dict[str, Any]:
    return {
        "id": vehicle.id,
        "name": vehicle.name,
        "nation": vehicle.nation.slug,
        "class": vehicle.vehicle_class.name,
        "rank": vehicle.rank_id,
        "type": vehicle.type_str,
        "is_reserve": vehicle.is_reserve,
        "availability": vehicle.availability,
        "tree_column": vehicle.tree_column,
        "tree_order": vehicle.tree_order,
        "br": {"ab": vehicle.br_ab, "rb": vehicle.br_rb, "sb": vehicle.br_sb},
        "rp_multiplier": vehicle.rp_multiplier,
        "rp_cost": vehicle.rp_cost,
        "ge_cost": vehicle.ge_cost,
        "gjn_cost": vehicle.gjn_cost,
        "marketplace_item_id": vehicle.marketplace_item_id,
        "folder_of": vehicle.folder_of,
    }


def research_column_count(rows: list[Vehicle], edges: list[VehicleEdge]) -> int:
    columns = sorted({item.tree_column for item in rows if item.tree_column is not None})
    if not columns:
        return 0
    edge_vehicle_ids = {vehicle_id for edge in edges for vehicle_id in (edge.parent_id, edge.child_id)}
    main_columns: set[int] = set()
    for column in columns:
        column_rows = [item for item in rows if item.tree_column == column]
        tree_count = sum(item.is_tree for item in column_rows)
        if tree_count > len(column_rows) - tree_count:
            main_columns.add(column)
        if any(item.is_tree and item.id in edge_vehicle_ids for item in column_rows):
            main_columns.add(column)
    if not main_columns:
        return len(columns)
    last_main_column = max(main_columns)
    return sum(column <= last_main_column for column in columns)
