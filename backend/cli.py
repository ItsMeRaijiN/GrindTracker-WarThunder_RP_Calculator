from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from database import SessionLocal, init_db
from datamine import DatamineError, build_normalized_snapshot, download_snapshot
from importer import import_from_json_dict, import_from_json_file


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="GrindTracker database tools")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="Create missing database tables")
    importer = subparsers.add_parser("import-json", help="Import normalized vehicle data")
    importer.add_argument("path")
    datamine = subparsers.add_parser("sync-datamine", help="Download, validate and publish War Thunder trees")
    datamine.add_argument("--source", type=Path, help="Local War-Thunder-Datamine checkout or cached snapshot")
    datamine.add_argument("--cache", type=Path, default=Path("instance/datamine"))
    datamine.add_argument("--ref", default="master", help="Git commit, branch or tag (default: master)")
    datamine.add_argument("--language", default="English", help="units.csv language column (default: English)")
    datamine.add_argument("--minimum-vehicles", type=int, default=2500)
    datamine.add_argument("--export", type=Path, help="Also write the normalized JSON snapshot")
    datamine.add_argument("--dry-run", action="store_true", help="Parse and validate without changing the database")
    args = parser.parse_args(argv)

    if args.command == "init-db":
        init_db()
        print("Database initialized.")
        return
    if args.command == "sync-datamine":
        try:
            source = args.source or download_snapshot(args.cache, args.ref)
            data = build_normalized_snapshot(
                source,
                language=args.language,
                minimum_vehicles=max(1, args.minimum_vehicles),
            )
        except DatamineError as exc:
            parser.error(str(exc))
        if args.export:
            args.export.parent.mkdir(parents=True, exist_ok=True)
            args.export.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.dry_run:
            summary = {"source_path": str(source), **data["snapshot"], **data["validation"]}
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return
        init_db()
        with SessionLocal() as session:
            report = import_from_json_dict(session, data)
        print(json.dumps({"source_path": str(source), **data["snapshot"], **report}, ensure_ascii=False, indent=2))
        return
    init_db()
    with SessionLocal() as session:
        print(json.dumps(import_from_json_file(session, args.path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
