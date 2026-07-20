from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Vehicle, VehicleEdge

PREMIUM_MAX_TARGET_RANK_OFFSET = 1
TARGET_ABOVE_EFFICIENCY = {0: 1.0, 1: 1.0, 2: 0.4, 3: 0.3}
TARGET_ABOVE_DEFAULT = 0.2
TARGET_BELOW_EFFICIENCY = {1: 0.9, 2: 0.3, 3: 0.1}
TARGET_BELOW_DEFAULT = 0.05


@dataclass(frozen=True)
class Forecast:
    avg_rp_per_battle: float
    avg_battle_minutes: float
    rp_is_base: bool = False
    has_premium: bool = False
    booster_percent: int = 0
    skill_bonus_percent: int = 0
    has_talisman: bool = False
    game_mode: str = "rb"


@dataclass(frozen=True)
class RpCalculation:
    effective_rp: float
    vehicle_multiplier: float
    economy_multiplier: float
    research_efficiency: float
    direct_predecessor_bonus: bool


def rank_efficiency(research_vehicle: Vehicle, target: Vehicle) -> float:
    """Return the official rank-difference research efficiency multiplier."""
    source_rank = research_vehicle.rank_id
    target_rank = target.rank_id
    if research_vehicle.is_premium and target_rank <= source_rank + PREMIUM_MAX_TARGET_RANK_OFFSET:
        return 1.0
    difference = target_rank - source_rank
    if difference >= 0:
        return TARGET_ABOVE_EFFICIENCY.get(difference, TARGET_ABOVE_DEFAULT)
    return TARGET_BELOW_EFFICIENCY.get(abs(difference), TARGET_BELOW_DEFAULT)


def rank_efficiency_rules() -> dict[str, Any]:
    """Expose the calculator's rules to clients that rank default research vehicles."""
    return {
        "premium_max_target_rank_offset": PREMIUM_MAX_TARGET_RANK_OFFSET,
        "target_above": {str(key): value for key, value in TARGET_ABOVE_EFFICIENCY.items()},
        "target_above_default": TARGET_ABOVE_DEFAULT,
        "target_below": {str(key): value for key, value in TARGET_BELOW_EFFICIENCY.items()},
        "target_below_default": TARGET_BELOW_DEFAULT,
    }


def effective_rp_per_battle(
    forecast: Forecast,
    research_vehicle: Vehicle | None = None,
    target: Vehicle | None = None,
    *,
    direct_predecessor: bool = False,
) -> RpCalculation:
    """Calculate RP once, separating already-observed and base-RP inputs.

    Observed RP already includes vehicle, account, talisman, booster, and skill
    multipliers. Base RP expands all of them. Research efficiency is target-
    specific and is therefore applied in both modes.
    """
    value = max(0.0, forecast.avg_rp_per_battle)
    vehicle_multiplier = max(0.0, float(research_vehicle.rp_multiplier or 1.0)) if research_vehicle else 1.0
    account_bonus = 1.0 if forecast.has_premium else 0.0
    booster_bonus = max(0, forecast.booster_percent) / 100.0
    skill_bonus = max(0, forecast.skill_bonus_percent) / 100.0
    talisman_bonus = 1.0 if forecast.has_talisman else 0.0
    economy_multiplier = 1.0 + account_bonus + booster_bonus + skill_bonus + talisman_bonus

    if forecast.rp_is_base:
        value *= vehicle_multiplier * economy_multiplier

    if direct_predecessor:
        efficiency = 1.3 if forecast.game_mode == "ab" else 1.1
    elif research_vehicle is not None and target is not None:
        efficiency = rank_efficiency(research_vehicle, target)
    else:
        efficiency = 1.0
    value *= efficiency
    return RpCalculation(
        effective_rp=value,
        vehicle_multiplier=vehicle_multiplier,
        economy_multiplier=economy_multiplier,
        research_efficiency=efficiency,
        direct_predecessor_bonus=direct_predecessor,
    )


def summarize_recent_battles(rows: list[dict[str, Any]]) -> tuple[float, float, int]:
    valid = [row for row in rows[:5] if float(row.get("rp") or 0) > 0]
    if not valid:
        return 0.0, 9.0, 0
    avg_rp = sum(float(row["rp"]) for row in valid) / len(valid)
    durations = [float(row.get("minutes") or 0) for row in valid if float(row.get("minutes") or 0) > 0]
    avg_minutes = sum(durations) / len(durations) if durations else 9.0
    return avg_rp, avg_minutes, len(valid)


def prerequisites_for(session: Session, vehicle_id: int) -> list[int]:
    vehicle = cast(Vehicle | None, session.get(Vehicle, vehicle_id))
    if vehicle is None:
        return []
    edge_parents = session.scalars(select(VehicleEdge.parent_id).where(VehicleEdge.child_id == vehicle_id)).all()
    parents = set(edge_parents)
    if vehicle.folder_of:
        parents.add(vehicle.folder_of)
    return sorted(parents)


def is_direct_predecessor(session: Session, research_vehicle_id: int, target_id: int) -> bool:
    return bool(
        session.scalar(
            select(VehicleEdge.id).where(
                VehicleEdge.parent_id == research_vehicle_id,
                VehicleEdge.child_id == target_id,
            )
        )
    )


def prerequisite_graph(session: Session) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
    """Load the active prerequisite graph with a fixed number of queries."""
    vehicle_rows = session.execute(select(Vehicle.id, Vehicle.folder_of).where(Vehicle.retired_at.is_(None))).all()
    vehicle_ids = {vehicle_id for vehicle_id, _ in vehicle_rows}
    edge_rows = (
        session.execute(
            select(VehicleEdge.parent_id, VehicleEdge.child_id).where(
                VehicleEdge.parent_id.in_(vehicle_ids),
                VehicleEdge.child_id.in_(vehicle_ids),
            )
        ).all()
        if vehicle_ids
        else []
    )
    edge_parents: dict[int, set[int]] = {}
    parents: dict[int, set[int]] = {}
    for parent_id, child_id in edge_rows:
        edge_parents.setdefault(child_id, set()).add(parent_id)
        parents.setdefault(child_id, set()).add(parent_id)
    for vehicle_id, folder_of in vehicle_rows:
        if folder_of in vehicle_ids:
            parents.setdefault(vehicle_id, set()).add(folder_of)
    return parents, edge_parents


def collect_prerequisites(vehicle_id: int, parents: dict[int, set[int]]) -> list[int]:
    found: set[int] = set()
    pending = [vehicle_id]
    while pending:
        current = pending.pop()
        for parent in parents.get(current, set()):
            if parent == vehicle_id or parent in found:
                continue
            found.add(parent)
            pending.append(parent)
    return sorted(found)


def _time_estimate(
    rp_remaining: int,
    effective: float,
    average_minutes: float,
) -> tuple[int | None, int | None, float | None]:
    if rp_remaining == 0:
        return 0, 0, 0.0
    if effective <= 0:
        return None, None, None
    battles = math.ceil(rp_remaining / effective)
    minutes = round(battles * max(0.0, average_minutes))
    return battles, minutes, round(minutes / 60, 2)


def estimate_vehicle(
    session: Session,
    vehicle: Vehicle,
    current_rp: int,
    forecast: Forecast,
    samples: int,
    research_vehicle: Vehicle | None = None,
) -> dict[str, Any]:
    total = max(0, int(vehicle.rp_cost or 0))
    current = min(max(0, current_rp), total)
    remaining = total - current
    direct = bool(research_vehicle and is_direct_predecessor(session, research_vehicle.id, vehicle.id))
    calculation = effective_rp_per_battle(forecast, research_vehicle, vehicle, direct_predecessor=direct)
    battles, minutes, hours = _time_estimate(remaining, calculation.effective_rp, forecast.avg_battle_minutes)
    requirement_ids = prerequisites_for(session, vehicle.id)
    requirements = (
        session.scalars(select(Vehicle).where(Vehicle.id.in_(requirement_ids))).all() if requirement_ids else []
    )
    return {
        "vehicle": vehicle_summary(vehicle),
        "research_vehicle": vehicle_summary(research_vehicle) if research_vehicle else None,
        "rp_current": current,
        "rp_remaining": remaining,
        "base_from_recent": average_summary(forecast, samples),
        "effective_rp_per_battle": round(calculation.effective_rp, 2),
        "modifiers": modifier_summary(calculation, forecast.rp_is_base),
        "battles_needed": battles,
        "minutes_needed": minutes,
        "hours_needed": hours,
        "ge_cost_by_rate": math.ceil(remaining / 45) if remaining else 0,
        "prerequisite_ids": requirement_ids,
        "prerequisites": [{"id": item.id, "name": item.name} for item in requirements],
    }


def estimate_cascade(
    session: Session,
    target: Vehicle,
    progress: dict[int, tuple[int, bool]],
    forecast: Forecast,
    samples: int,
    research_vehicle: Vehicle | None = None,
) -> dict[str, Any]:
    parents, edge_parents = prerequisite_graph(session)
    required_ids = [*collect_prerequisites(target.id, parents), target.id]
    vehicles = list(session.scalars(select(Vehicle).where(Vehicle.id.in_(required_ids))).all())
    vehicles.sort(key=lambda item: (item.rank_id, item.tree_column or 0, item.tree_order or 0, item.name))
    breakdown: list[dict[str, Any]] = []
    total_remaining = 0
    total_battles = 0
    has_unknown_estimate = False
    target_calculation: RpCalculation | None = None

    for vehicle in vehicles:
        total = max(0, int(vehicle.rp_cost or 0))
        current, done = progress.get(vehicle.id, (0, False))
        done = done or vehicle.is_reserve
        current = min(max(0, current), total)
        remaining = 0 if done else total - current
        total_remaining += remaining
        direct = bool(research_vehicle and research_vehicle.id in edge_parents.get(vehicle.id, set()))
        calculation = effective_rp_per_battle(forecast, research_vehicle, vehicle, direct_predecessor=direct)
        if vehicle.id == target.id:
            target_calculation = calculation
        battles, _, _ = _time_estimate(remaining, calculation.effective_rp, forecast.avg_battle_minutes)
        if battles is None:
            has_unknown_estimate = has_unknown_estimate or remaining > 0
        else:
            total_battles += battles
        breakdown.append(
            {
                "id": vehicle.id,
                "name": vehicle.name,
                "rank": vehicle.rank_id,
                "rp_cost": total,
                "rp_current": current,
                "rp_remaining": remaining,
                "done": done,
                "effective_rp_per_battle": round(calculation.effective_rp, 2),
                "research_efficiency": calculation.research_efficiency,
                "direct_predecessor_bonus": calculation.direct_predecessor_bonus,
            }
        )

    target_result = target_calculation or effective_rp_per_battle(forecast, research_vehicle, target)
    battles_needed = None if has_unknown_estimate else total_battles
    minutes_needed = None
    hours_needed = None
    if battles_needed is not None:
        minutes_needed = round(battles_needed * max(0.0, forecast.avg_battle_minutes))
        hours_needed = round(minutes_needed / 60, 2)
    return {
        "target": {"id": target.id, "name": target.name},
        "research_vehicle": vehicle_summary(research_vehicle) if research_vehicle else None,
        "base_from_recent": average_summary(forecast, samples),
        "effective_rp_per_battle": round(target_result.effective_rp, 2),
        "modifiers": modifier_summary(target_result, forecast.rp_is_base),
        "required_ids": required_ids,
        "breakdown": breakdown,
        "rp_total_remaining": total_remaining,
        "battles_needed": battles_needed,
        "minutes_needed": minutes_needed,
        "hours_needed": hours_needed,
        "ge_cost_by_rate": math.ceil(total_remaining / 45) if total_remaining else 0,
    }


def modifier_summary(calculation: RpCalculation, base_mode: bool) -> dict[str, Any]:
    return {
        "vehicle_rp_multiplier": calculation.vehicle_multiplier,
        "vehicle_rp_multiplier_applied": base_mode,
        "economy_multiplier": calculation.economy_multiplier,
        "research_efficiency": calculation.research_efficiency,
        "direct_predecessor_bonus": calculation.direct_predecessor_bonus,
    }


def average_summary(forecast: Forecast, samples: int) -> dict[str, Any]:
    return {
        "avg_rp_per_battle": round(forecast.avg_rp_per_battle, 2),
        "avg_battle_minutes": round(forecast.avg_battle_minutes, 2),
        "samples": samples,
        "rp_is_base": forecast.rp_is_base,
    }


def vehicle_summary(vehicle: Vehicle) -> dict[str, Any]:
    return {
        "id": vehicle.id,
        "name": vehicle.name,
        "rank": vehicle.rank_id,
        "type": vehicle.type_str,
        "rp_cost": vehicle.rp_cost,
        "ge_cost": vehicle.ge_cost,
        "rp_multiplier": vehicle.rp_multiplier,
    }
