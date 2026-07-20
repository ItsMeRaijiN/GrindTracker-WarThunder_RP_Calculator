from __future__ import annotations

TEMPORARY_VARIANT_PREFIXES = ("nt_",)
TEMPORARY_VARIANT_SUFFIXES = ("_killstreak", "_race")


def is_temporary_variant(source_key: str | None, availability: str | None = None) -> bool:
    """Identify mission-only copies that are not persistent player vehicles."""
    if not source_key:
        return False
    normalized = source_key.strip().casefold()
    if normalized.startswith(TEMPORARY_VARIANT_PREFIXES) or normalized.endswith(TEMPORARY_VARIANT_SUFFIXES):
        return True
    normalized_availability = (availability or "").strip().casefold()
    return normalized.endswith("_event") and normalized_availability in {"", "unavailable"}
