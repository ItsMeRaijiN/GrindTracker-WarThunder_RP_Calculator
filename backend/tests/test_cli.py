from __future__ import annotations

import json

import pytest

import cli


def test_datamine_dry_run_does_not_initialize_the_database(monkeypatch, capsys, tmp_path):
    snapshot = {
        "snapshot": {"source": "fixture", "version": "1", "revision": "abc"},
        "validation": {"vehicle_count": 1, "edge_count": 0, "warning_count": 0},
    }

    def unexpected_init() -> None:
        pytest.fail("dry-run must not initialize or migrate the database")

    monkeypatch.setattr(cli, "init_db", unexpected_init)
    monkeypatch.setattr(cli, "build_normalized_snapshot", lambda *_args, **_kwargs: snapshot)

    cli.main(["sync-datamine", "--source", str(tmp_path), "--minimum-vehicles", "1", "--dry-run"])

    output = json.loads(capsys.readouterr().out)
    assert output["source_path"] == str(tmp_path)
    assert output["source"] == "fixture"
    assert output["vehicle_count"] == 1
