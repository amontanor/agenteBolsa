"""Run one digest-route module with explicit test guards.

Used only by the Oct10 local measurement script.  It forces Settings to use
``_env_file=None`` and blocks network/DNS before importing the target module.
"""

from __future__ import annotations

import ctypes
import importlib
import json
import os
import sys
from ctypes import wintypes
from datetime import date as RealDate
from datetime import datetime as RealDateTime


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _rss() -> dict[str, int | str] | None:
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = []
    get_current_process.restype = wintypes.HANDLE
    get_info = psapi.GetProcessMemoryInfo
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessMemoryCounters), wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not get_info(get_current_process(), ctypes.byref(counters), counters.cb):
        return None
    return {
        "pid": os.getpid(),
        "sys_prefix": sys.prefix,
        "working_set_bytes": int(counters.WorkingSetSize),
        "peak_working_set_bytes": int(counters.PeakWorkingSetSize),
    }


def _phase(name: str, module: str) -> None:
    print(
        "DIGEST_PHASE "
        + json.dumps(
            {
                "phase": name,
                "module": module,
                "rss": _rss(),
                "module_count": len(sys.modules),
            },
            sort_keys=True,
        ),
        file=sys.stderr,
        flush=True,
    )


def _block_network() -> None:
    import socket

    def blocked(*_args, **_kwargs):
        raise RuntimeError("network_blocked_by_oct10_digest_harness")

    socket.create_connection = blocked
    socket.getaddrinfo = blocked
    socket.gethostbyname = blocked
    socket.gethostbyname_ex = blocked
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked


def _settings_without_env_file():
    from agente_bolsa import config

    base_settings = config.Settings

    class IsolatedSettings(base_settings):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("_env_file", None)
            super().__init__(*args, **kwargs)

    config.Settings = IsolatedSettings

    def guarded_get_settings():
        settings = IsolatedSettings()
        settings.ensure_runtime_dirs()
        return settings

    config.get_settings = guarded_get_settings
    return config


def _guard_status(config) -> dict[str, object]:
    import socket

    status: dict[str, object] = {"env_file": None}
    settings = config.Settings()
    status["data_dir"] = str(settings.data_dir)
    try:
        socket.getaddrinfo("example.invalid", 443)
    except RuntimeError as exc:
        status["dns_blocked"] = str(exc) == "network_blocked_by_oct10_digest_harness"
    else:
        status["dns_blocked"] = False
    return status


def _seed_fixture(config) -> None:
    """Seed one bounded recommendation through the existing Store schema."""

    from agente_bolsa.storage import Store

    settings = config.Settings()
    store = Store(settings.database_path, settings.agent_logs_dir)
    try:
        store.ensure_schema()
        store.save_trade_recommendation(
            recommendation_id="oct10-fixture-recommendation",
            cycle_id="oct10-fixture-cycle",
            symbol="SYNTH",
            action="hold",
            confidence=0.75,
            payload={"fixture": True, "source": "isolated_oct10"},
        )
    finally:
        close = getattr(store, "close_read_connection", None)
        if callable(close):
            close()


def _freeze_loaded_clocks() -> None:
    """Freeze datetime/date names already imported by the application modules."""

    from datetime import timezone

    fixed = RealDateTime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)

    class FrozenDateTime(RealDateTime):
        @classmethod
        def now(cls, tz=None):
            return fixed.replace(tzinfo=None) if tz is None else fixed.astimezone(tz)

        @classmethod
        def today(cls):
            return fixed.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return fixed.replace(tzinfo=None)

    class FrozenDate(RealDate):
        @classmethod
        def today(cls):
            return fixed.date()

    for loaded in list(sys.modules.values()):
        if loaded is None or not getattr(loaded, "__name__", "").startswith("agente_bolsa."):
            continue
        if getattr(loaded, "datetime", None) is RealDateTime:
            loaded.datetime = FrozenDateTime
        if getattr(loaded, "date", None) is RealDate:
            loaded.date = FrozenDate


def _prepare_route(module_name: str, config) -> None:
    # digest_cli imports its business modules lazily inside main().  Preload
    # only those existing modules so the frozen clock applies before dispatch;
    # this does not alter the production route.
    if module_name == "agente_bolsa.digest_cli":
        importlib.import_module("agente_bolsa.continuous_improvement.digest")
        importlib.import_module("agente_bolsa.tools.config_audit")
        importlib.import_module("agente_bolsa.storage")
    _freeze_loaded_clocks()
    if os.environ.get("DIGEST_ROUTE_FIXTURE") == "1":
        _seed_fixture(config)


def main() -> None:
    _block_network()
    config = _settings_without_env_file()
    module_name = os.environ["DIGEST_ROUTE_MODULE"]
    import_only = os.environ.get("DIGEST_ROUTE_IMPORT_ONLY") == "1"
    sys.argv = [module_name, *sys.argv[1:]]
    _phase("before_import", module_name)
    module = importlib.import_module(module_name)
    _phase("imported", module_name)
    if import_only:
        print(
            json.dumps(
                {
                    "module": module_name,
                    "module_count": len(sys.modules),
                    "main_loaded": "agente_bolsa.main" in sys.modules,
                    "scheduler_loaded": "agente_bolsa.scheduler" in sys.modules,
                    "runtime_loaded": "agente_bolsa.continuous_improvement.runtime" in sys.modules,
                    "guards": _guard_status(config),
                }
            )
        )
        return
    _prepare_route(module_name, config)
    _phase("prepared", module_name)
    module.main()
    _phase("completed", module_name)


if __name__ == "__main__":
    main()
