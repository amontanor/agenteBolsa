import hashlib
import json

from scripts.raspberry_preflight import build_report, parse_args


def _healthy_observations() -> dict[str, str]:
    observations = {
        "host": "Raspberryi5",
        "arch": "aarch64",
        "uptime_seconds": "3600",
        "mount": "/dev/sda1 ext4 rw,noatime",
        "block": 'NAME="sda1" UUID="1a8cb7c0-3a65-4d72-866f-340db4c6bafc"',
        "disk": "/dev/sda1 100 10 90000000000 10% /var/lib/agente-bolsa",
        "inode": "/dev/sda1 100 10 90 10% /var/lib/agente-bolsa",
        "memory": "Mem: 2000000000 500000000 1500000000 0 0 1500000000",
        "kernel_storage": "",
        "d_state": "",
        "services": ";".join(
            f"{name}|agente-bolsa:0.4.229-arm64|Up 10 minutes (healthy)|"
            for name in (
                "agente-bolsa-scheduler-1",
                "agente-bolsa-auxiliary-1",
                "agente-bolsa-web-1",
            )
        ),
        "image.agente-bolsa:0.4.230-arm64": "sha256:candidate|arm64|created|42b8dfc1",
        "sqlite_files": "/var/lib/agente-bolsa/state/agente_bolsa.sqlite3|100|rw-------|antonio:antonio;",
    }
    for name in (
        "agente-bolsa-scheduler-1",
        "agente-bolsa-auxiliary-1",
        "agente-bolsa-web-1",
    ):
        observations[f"inspect.{name}"] = "running|healthy|0|agente-bolsa:0.4.229-arm64|started"
        observations[f"flags.{name}"] = ";".join(
            [
                "TRADING_MODE=paper",
                "ALPACA_PAPER=true",
                "AUTO_PAPER_TRADING=true",
                "REQUIRE_HUMAN_APPROVAL=false",
                "ALLOW_LIVE_TRADING=false",
                "ALLOW_AUTO_APPLY_IMPROVEMENTS=false",
            ]
        )
    return observations


def test_preflight_keeps_sqlite_integrity_blocked_until_cold_snapshot():
    args = parse_args([])
    report = build_report(args, _healthy_observations(), None)

    assert report["ok"] is False
    assert report["checks"]["usb_mount"]["ok"] is True
    assert report["checks"]["docker_core_health"]["ok"] is True
    assert report["checks"]["sqlite_integrity"]["ok"] is False
    assert report["checks"]["inode_space"]["ok"] is True
    assert any("sqlite_integrity" in reason for reason in report["blocking_reasons"])
    assert report["mutations"] == []


def test_preflight_accepts_a_validated_cold_snapshot_receipt(tmp_path):
    snapshot = tmp_path / "agente_bolsa.sqlite3"
    snapshot.write_bytes(b"validated snapshot")
    snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    receipt = tmp_path / "sqlite-cold-snapshot.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "p-l89.sqlite-cold-snapshot.v1",
                "status": "ok",
                "quick_check": "ok",
                "integrity_check": "ok",
                "source_host": "Raspberryi5",
                "mount": "/var/lib/agente-bolsa",
                "device_uuid": "1a8cb7c0-3a65-4d72-866f-340db4c6bafc",
                "source_path": r"C:\data\agente_bolsa.sqlite3",
                "snapshot_path": str(snapshot),
                "sha256": snapshot_hash,
                "files": {
                    "agente_bolsa.sqlite3": {
                        "size": snapshot.stat().st_size,
                        "sha256": snapshot_hash,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    args = parse_args(["--sqlite-receipt", str(receipt)])

    report = build_report(args, _healthy_observations(), None)

    assert report["ok"] is True
    assert report["checks"]["sqlite_integrity"]["ok"] is True


def test_preflight_rejects_receipt_when_snapshot_hash_differs(tmp_path):
    snapshot = tmp_path / "agente_bolsa.sqlite3"
    snapshot.write_bytes(b"actual snapshot")
    receipt = tmp_path / "sqlite-cold-snapshot.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "p-l89.sqlite-cold-snapshot.v1",
                "status": "ok",
                "quick_check": "ok",
                "integrity_check": "ok",
                "source_host": "Raspberryi5",
                "mount": "/var/lib/agente-bolsa",
                "device_uuid": "1a8cb7c0-3a65-4d72-866f-340db4c6bafc",
                "source_path": r"C:\data\agente_bolsa.sqlite3",
                "snapshot_path": str(snapshot),
                "sha256": "0" * 64,
                "files": {
                    "agente_bolsa.sqlite3": {"size": snapshot.stat().st_size, "sha256": "0" * 64}
                },
            }
        ),
        encoding="utf-8",
    )

    report = build_report(parse_args(["--sqlite-receipt", str(receipt)]), _healthy_observations(), None)

    assert report["checks"]["sqlite_integrity"]["ok"] is False


def test_preflight_requires_paper_flags_on_each_core_container(tmp_path):
    observations = _healthy_observations()
    observations["flags.agente-bolsa-auxiliary-1"] = "TRADING_MODE=paper"

    report = build_report(parse_args([]), observations, None)

    assert report["checks"]["paper_policy"]["ok"] is False
    assert "agente-bolsa-auxiliary-1" in report["checks"]["paper_policy"]["detail"]


def test_preflight_blocks_inode_pressure():
    observations = _healthy_observations()
    observations["inode"] = "/dev/sda1 100 95 5 95% /var/lib/agente-bolsa"

    report = build_report(parse_args([]), observations, None)

    assert report["checks"]["inode_space"]["ok"] is False


def test_preflight_blocks_recent_storage_and_blocked_io():
    args = parse_args(["--min-uptime-seconds", "600"])
    observations = _healthy_observations()
    observations["uptime_seconds"] = "30"
    observations["kernel_storage"] = "EXT4-fs error"
    observations["d_state"] = "D 42 python"

    report = build_report(args, observations, None)

    assert report["checks"]["host_stability"]["ok"] is False
    assert report["checks"]["kernel_storage"]["ok"] is False
    assert report["checks"]["no_blocked_io_process"]["ok"] is False
