import sqlite3

import pytest

from scripts.sqlite_cold_snapshot import create_snapshot, parse_args


def _args(source, destination, writers_stopped=False):
    values = [
        "--source",
        str(source),
        "--destination-dir",
        str(destination),
        "--source-host",
        "Windows-Productivo",
        "--target-host",
        "Raspberryi5",
        "--target-mount",
        "/var/lib/agente-bolsa",
        "--target-device-uuid",
        "1a8cb7c0-3a65-4d72-866f-340db4c6bafc",
    ]
    if writers_stopped:
        values.append("--writers-stopped")
    return parse_args(values)


def test_snapshot_requires_explicit_writer_quiescence(tmp_path):
    source = tmp_path / "agente_bolsa.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('ok')")

    with pytest.raises(ValueError, match="writers-stopped"):
        create_snapshot(_args(source, tmp_path / "snapshot"))


def test_snapshot_copies_and_validates_sqlite_file_set(tmp_path):
    source = tmp_path / "agente_bolsa.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('ok')")

    destination = tmp_path / "snapshot"
    receipt = create_snapshot(_args(source, destination, writers_stopped=True))

    assert receipt["schema"] == "p-l89.sqlite-cold-snapshot.v2"
    assert receipt["source_host"] == "Windows-Productivo"
    assert receipt["target_host"] == "Raspberryi5"
    assert receipt["snapshot_path"] == str(destination / source.name)
    assert receipt["status"] == "ok"
    assert receipt["quick_check"] == "ok"
    assert receipt["integrity_check"] == "ok"
    assert receipt["sha256"] == receipt["files"][source.name]["sha256"]
    assert (destination / source.name).is_file()
    assert (destination / "receipt.json").is_file()


def test_snapshot_never_overwrites_existing_destination(tmp_path):
    source = tmp_path / "agente_bolsa.sqlite3"
    source.touch()
    destination = tmp_path / "snapshot"
    destination.mkdir()

    with pytest.raises(FileExistsError, match="no se sobrescribe"):
        create_snapshot(_args(source, destination, writers_stopped=True))
