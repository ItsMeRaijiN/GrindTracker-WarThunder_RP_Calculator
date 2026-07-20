from __future__ import annotations

import csv
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, deque
from pathlib import Path
from typing import Any

from catalog import is_temporary_variant

DATAMINE_REPOSITORY = "https://github.com/gszabi99/War-Thunder-Datamine"
RAW_ROOT = "https://raw.githubusercontent.com/gszabi99/War-Thunder-Datamine"
API_ROOT = "https://api.github.com/repos/gszabi99/War-Thunder-Datamine"
SOURCE_NAME = "war-thunder-datamine"

FILES = {
    "shop": Path("char.vromfs.bin_u/config/shop.blkx"),
    "wpcost": Path("char.vromfs.bin_u/config/wpcost.blkx"),
    "units": Path("lang.vromfs.bin_u/lang/units.csv"),
    "version": Path("version"),
}
FILE_SIZE_LIMITS = {
    "shop": 20 * 1024 * 1024,
    "wpcost": 100 * 1024 * 1024,
    "units": 30 * 1024 * 1024,
    "version": 1024,
}

NATIONS = {
    "country_usa": ("usa", "USA"),
    "country_germany": ("germany", "Germany"),
    "country_ussr": ("ussr", "USSR"),
    "country_britain": ("britain", "Great Britain"),
    "country_japan": ("japan", "Japan"),
    "country_china": ("china", "China"),
    "country_italy": ("italy", "Italy"),
    "country_france": ("france", "France"),
    "country_sweden": ("sweden", "Sweden"),
    "country_israel": ("israel", "Israel"),
}

TREE_CLASSES = {
    "army": "army",
    "helicopters": "helicopter",
    "aviation": "aviation",
    "ships": "bluewater",
    "boats": "coastal",
}

ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")
USER_AGENT = "GrindTracker-datamine-importer/1.0"


class DatamineError(RuntimeError):
    pass


class DatamineValidationError(DatamineError):
    pass


def _request_json(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise DatamineError("GitHub returned an invalid JSON response.")
    return payload


def resolve_revision(ref: str = "master", timeout: int = 30) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref
    try:
        encoded_ref = urllib.parse.quote(ref, safe="")
        payload = _request_json(f"{API_ROOT}/commits/{encoded_ref}", timeout)
        revision = str(payload.get("sha") or "")
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise DatamineError("GitHub returned an invalid datamine revision.")
        return revision
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        raise DatamineError(f"Could not resolve datamine ref {ref!r}: {exc}") from exc


def download_snapshot(cache_dir: str | Path, ref: str = "master", timeout: int = 120) -> Path:
    """Download only the four files needed by GrindTracker"""
    revision = resolve_revision(ref, min(timeout, 30))
    destination = Path(cache_dir).resolve() / revision
    marker = destination / ".grindtracker-complete"
    if marker.exists() and all((destination / relative).is_file() for relative in FILES.values()):
        return destination

    destination.mkdir(parents=True, exist_ok=True)
    try:
        for name, relative in FILES.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(  # noqa: S310
                f"{RAW_ROOT}/{revision}/{relative.as_posix()}",
                headers={"User-Agent": USER_AGENT},
            )
            temporary = target.with_suffix(f"{target.suffix}.part")
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response, temporary.open("wb") as handle:  # noqa: S310
                    copied = 0
                    while chunk := response.read(1024 * 1024):
                        copied += len(chunk)
                        if copied > FILE_SIZE_LIMITS[name]:
                            raise DatamineError(f"Datamine file {relative.as_posix()} exceeds its safety limit.")
                        handle.write(chunk)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
            temporary.replace(target)
        (destination / ".grindtracker-revision").write_text(revision, encoding="ascii")
        marker.write_text("ok\n", encoding="ascii")
    except (OSError, urllib.error.HTTPError) as exc:
        raise DatamineError(f"Could not download datamine snapshot {revision}: {exc}") from exc
    return destination


def source_files(root: str | Path) -> dict[str, Path]:
    base = Path(root).resolve()
    result = {name: base / relative for name, relative in FILES.items()}
    missing = [path.relative_to(base).as_posix() for path in result.values() if not path.is_file()]
    if missing:
        raise DatamineError(f"Datamine source is incomplete. Missing: {', '.join(missing)}")
    return result


def _localization(path: Path, language: str) -> tuple[dict[str, str], int]:
    values: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.reader(handle, delimiter=";")
        try:
            header = next(rows)
        except StopIteration as exc:
            raise DatamineValidationError("units.csv is empty.") from exc
        try:
            english_index = header.index("<English>")
        except ValueError as exc:
            raise DatamineValidationError("units.csv does not contain the required <English> column.") from exc
        requested = f"<{language}>"
        language_index = header.index(requested) if requested in header else english_index
        fallback_count = 0
        for row in rows:
            if not row or not row[0]:
                continue
            translated = row[language_index].strip() if len(row) > language_index else ""
            english = row[english_index].strip() if len(row) > english_index else ""
            if not translated and english:
                fallback_count += 1
            values[row[0]] = translated or english
    return values, fallback_count


def _display_name(localization: dict[str, str], key: str) -> tuple[str, bool]:
    for suffix in ("_shop", "_0", "_1"):
        value = localization.get(f"{key}{suffix}", "").strip()
        if value:
            return value, False
    return key.replace("_", " ").strip().title(), True


def _battle_rating(value: Any) -> float | None:
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return None
    if rank < 0:
        return None
    return round(1 + rank / 3, 1)


def _gold_cost(record: dict[str, Any]) -> int:
    try:
        return max(0, int(record.get("costGold") or 0))
    except (TypeError, ValueError):
        return 0


def _availability(record: dict[str, Any]) -> tuple[str, str, str]:
    """Return gameplay type, acquisition channel, and research type."""
    if record.get("isClanVehicle"):
        return "collector", "squadron", "squadron_rp"

    kind = "premium" if _gold_cost(record) else "collector"
    event = str(record.get("event") or "").strip().casefold()
    hidden = bool(record.get("showOnlyWhenBought") or record.get("hideUntilBought"))

    if event.startswith("battlepass_"):
        return kind, "battle_pass", "event_only"
    if event:
        return kind, "event", "event_only"
    if record.get("marketplaceItemdefId"):
        return kind, "marketplace", "marketplace"
    if record.get("gift"):
        availability = "pack" if str(record["gift"]).strip().casefold() == "store_pack" else "special"
        return kind, availability, availability
    if hidden:
        return kind, "unavailable", "unavailable"
    if record.get("showOnlyWhenAvailableForPurchase"):
        return kind, "limited", "limited"
    if _gold_cost(record):
        return "premium", "premium", "premium"
    return "tree", "researchable", "standard"


def _direct_ge_cost(record: dict[str, Any], availability: str) -> int | None:
    """Expose a GE price only for a direct or explicitly limited GE offer."""
    gold = _gold_cost(record)
    return gold if gold and availability in {"premium", "limited"} else None


def _marketplace_item_id(record: dict[str, Any]) -> int | None:
    try:
        item_id = int(record.get("marketplaceItemdefId") or 0)
    except (TypeError, ValueError):
        return None
    return item_id if item_id > 0 else None


def _role(value: Any) -> str | None:
    if not value:
        return None
    return str(value).removeprefix("exp_").lower()


def _children(key: str, value: Any) -> tuple[str | None, list[tuple[str, dict[str, Any]]], dict[str, Any]]:
    if not isinstance(value, dict):
        return None, [], {}
    if "rank" in value:
        return None, [(key, value)], {}
    children = [(child_key, child) for child_key, child in value.items() if isinstance(child, dict) and "rank" in child]
    metadata = {name: item for name, item in value.items() if name not in {child_key for child_key, _ in children}}
    folder = key if children else None
    return folder, children, metadata


def _checksum(files: dict[str, Path]) -> str:
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode("ascii"))
        with files[name].open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _assert_acyclic(edges: list[dict[str, Any]], keys: set[str]) -> None:
    successors: dict[str, list[str]] = {key: [] for key in keys}
    indegree = Counter({key: 0 for key in keys})
    for edge in edges:
        parent = str(edge["parent_key"])
        child = str(edge["child_key"])
        successors[parent].append(child)
        indegree[child] += 1
    pending = deque(key for key, degree in indegree.items() if degree == 0)
    visited = 0
    while pending:
        current = pending.popleft()
        visited += 1
        for child in successors[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                pending.append(child)
    if visited != len(keys):
        raise DatamineValidationError("The research dependency graph contains a cycle.")


def _normalized_vehicle(
    source_key: str,
    shop_record: dict[str, Any],
    group_metadata: dict[str, Any],
    economy: dict[str, Any],
    localization: dict[str, str],
    version: str,
    nation_slug: str,
    tree_class: str,
    column_index: int,
    tree_order: int,
    folder_key: str | None,
    folder_root: str | None,
    counters: Counter[str],
) -> tuple[dict[str, Any] | None, str | None]:
    economy_record = economy.get(source_key)
    if not isinstance(economy_record, dict):
        economy_record = {}
        counters["missing_economy"] += 1
    record = {**group_metadata, **shop_record, **economy_record}
    name, missing_name = _display_name(localization, source_key)
    counters["missing_localization"] += int(missing_name)
    kind, availability, research_type = _availability(record)
    rank = record.get("rank")
    if not isinstance(rank, int) or not 1 <= rank <= len(ROMAN):
        counters["invalid_rank"] += 1
        return None, None

    parent = record.get("reqAir")
    parent_key = parent.strip() if isinstance(parent, str) and parent.strip() else None
    rp_cost = record.get("reqExp")
    sl_cost = record.get("value")
    return {
        "key": source_key,
        "source": SOURCE_NAME,
        "source_version": version,
        "name": name,
        "nation": nation_slug,
        "class": tree_class,
        "role": _role(record.get("unitClass")),
        "rank": rank,
        "type": kind,
        "availability": availability,
        "research_type": research_type,
        "tree_column": column_index,
        "tree_order": tree_order,
        "folder_key": folder_key,
        "folder_of_key": folder_root if folder_root and folder_root != source_key else None,
        "br": {
            "ab": _battle_rating(record.get("economicRankArcade")),
            "rb": _battle_rating(record.get("economicRankHistorical")),
            "sb": _battle_rating(record.get("economicRankSimulation")),
        },
        "rp_multiplier": float(record["expMul"]) if isinstance(record.get("expMul"), (int, float)) else None,
        "rp_cost": int(rp_cost) if isinstance(rp_cost, (int, float)) and rp_cost >= 0 else None,
        "sl_cost": int(sl_cost) if isinstance(sl_cost, (int, float)) and sl_cost >= 0 else None,
        "ge_cost": _direct_ge_cost(record, availability),
        "marketplace_item_id": _marketplace_item_id(record),
        "wiki_url": f"https://wiki.warthunder.com/unit/{source_key}",
    }, parent_key


def _collect_vehicles(
    shop: dict[str, Any],
    economy: dict[str, Any],
    localization: dict[str, str],
    version: str,
    counters: Counter[str],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    vehicles: list[dict[str, Any]] = []
    parent_candidates: dict[str, str] = {}
    seen: set[str] = set()
    for country_key, nation_data in shop.items():
        if country_key not in NATIONS or not isinstance(nation_data, dict):
            if country_key.startswith("country_"):
                counters["unknown_nations"] += 1
            continue
        nation_slug, _ = NATIONS[country_key]
        for source_class, tree_data in nation_data.items():
            tree_class = TREE_CLASSES.get(source_class)
            if tree_class is None or not isinstance(tree_data, dict):
                counters["unknown_classes"] += 1
                continue
            columns = tree_data.get("range")
            if not isinstance(columns, list):
                counters["invalid_trees"] += 1
                continue
            for column_index, column in enumerate(columns):
                if not isinstance(column, dict):
                    counters["invalid_columns"] += 1
                    continue
                tree_order = 0
                for entry_key, entry_value in column.items():
                    folder_key, children, group_metadata = _children(entry_key, entry_value)
                    if not children:
                        counters["empty_groups"] += 1
                        continue
                    folder_root = children[0][0] if folder_key else None
                    for source_key, shop_record in children:
                        if source_key in seen:
                            raise DatamineValidationError(f"Duplicate vehicle key in shop.blkx: {source_key}")
                        seen.add(source_key)
                        vehicle, parent = _normalized_vehicle(
                            source_key,
                            shop_record,
                            group_metadata,
                            economy,
                            localization,
                            version,
                            nation_slug,
                            tree_class,
                            column_index,
                            tree_order,
                            folder_key,
                            folder_root,
                            counters,
                        )
                        if vehicle is None:
                            continue
                        if is_temporary_variant(source_key, str(vehicle["availability"])):
                            counters["temporary_variants"] += 1
                            continue
                        vehicles.append(vehicle)
                        if parent:
                            parent_candidates[source_key] = parent
                        tree_order += 1
    return vehicles, parent_candidates


def build_normalized_snapshot(
    root: str | Path,
    *,
    language: str = "English",
    minimum_vehicles: int = 2500,
) -> dict[str, Any]:
    if minimum_vehicles < 1:
        raise DatamineValidationError("minimum_vehicles must be at least 1.")
    base = Path(root).resolve()
    files = source_files(base)
    try:
        with files["shop"].open("r", encoding="utf-8") as handle:
            shop = json.load(handle)
        with files["wpcost"].open("r", encoding="utf-8") as handle:
            economy = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise DatamineValidationError(f"Could not parse datamine JSON: {exc}") from exc
    if not isinstance(shop, dict) or not isinstance(economy, dict):
        raise DatamineValidationError("shop.blkx and wpcost.blkx must contain JSON objects.")

    localization, locale_fallbacks = _localization(files["units"], language)
    version = files["version"].read_text(encoding="utf-8-sig").strip()
    if not version:
        raise DatamineValidationError("The datamine version file is empty.")
    checksum = _checksum(files)
    revision_file = base / ".grindtracker-revision"
    pinned_revision = revision_file.read_text(encoding="ascii").strip() if revision_file.is_file() else None
    if pinned_revision and not re.fullmatch(r"[0-9a-f]{40}", pinned_revision):
        raise DatamineValidationError(".grindtracker-revision must contain a lowercase 40-character Git SHA.")
    revision = pinned_revision or f"{version}-{checksum[:12]}"

    counters: Counter[str] = Counter()
    vehicles, parent_candidates = _collect_vehicles(shop, economy, localization, version, counters)

    if len(vehicles) < minimum_vehicles:
        raise DatamineValidationError(
            f"Snapshot contains only {len(vehicles)} vehicles; expected at least {minimum_vehicles}. "
            "Use --minimum-vehicles only for fixtures or intentionally filtered sources."
        )

    keys = {str(vehicle["key"]) for vehicle in vehicles}
    edges: list[dict[str, Any]] = []
    for child, parent in parent_candidates.items():
        if parent not in keys:
            counters["unresolved_parents"] += 1
            continue
        edges.append({"parent_key": parent, "child_key": child})
    _assert_acyclic(edges, keys)

    warnings = [
        f"Missing localization for {counters['missing_localization']} vehicles; source identifiers were used."
        if counters["missing_localization"]
        else "",
        f"Missing economy data for {counters['missing_economy']} vehicles." if counters["missing_economy"] else "",
        f"Skipped {counters['unresolved_parents']} dependencies pointing outside the current trees."
        if counters["unresolved_parents"]
        else "",
        f"The {language} column had {locale_fallbacks} empty values; English fallback was used."
        if locale_fallbacks
        else "",
    ]
    warnings = [warning for warning in warnings if warning]
    ranks = sorted({int(vehicle["rank"]) for vehicle in vehicles})
    classes = [value for value in TREE_CLASSES.values() if any(vehicle["class"] == value for vehicle in vehicles)]
    nations = [
        {"slug": slug, "name": name}
        for country, (slug, name) in NATIONS.items()
        if country in shop and any(vehicle["nation"] == slug for vehicle in vehicles)
    ]
    return {
        "snapshot": {
            "source": SOURCE_NAME,
            "version": version,
            "revision": revision,
            "checksum": checksum,
            "source_url": f"{DATAMINE_REPOSITORY}/tree/{revision}" if pinned_revision else DATAMINE_REPOSITORY,
            "retire_missing": True,
        },
        "nations": nations,
        "classes": classes,
        "ranks": [{"id": rank, "label": ROMAN[rank - 1]} for rank in ranks],
        "vehicles": vehicles,
        "edges": edges,
        "warnings": warnings,
        "validation": {
            "vehicle_count": len(vehicles),
            "edge_count": len(edges),
            "warning_count": len(warnings),
            **dict(counters),
        },
    }
