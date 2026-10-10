"""Run one digest-route module with explicit test guards.

Used only by the Oct10 local measurement script.  It forces Settings to use
``_env_file=None`` and blocks network/DNS before importing the target module.
"""

from __future__ import annotations

import ctypes
import importlib
import json
import os
import struct
import sys


def _rss() -> int | None:
    if os.name != "nt":
        return None
    get_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_info.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    get_info.restype = ctypes.c_bool
    buffer = ctypes.create_string_buffer(256)
    size = ctypes.c_ulong(len(buffer))
    if not get_info(ctypes.windll.kernel32.GetCurrentProcess(), buffer, ctypes.byref(size)):
        return None
    return int(struct.unpack_from("<Q", buffer.raw, 16)[0])


def _phase(name: str, module: str) -> None:
    print(
        "DIGEST_PHASE "
        + json.dumps(
            {
                "phase": name,
                "module": module,
                "rss_bytes": _rss(),
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


def _settings_without_env_file() -> None:
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


def main() -> None:
    _block_network()
    _settings_without_env_file()
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
                }
            )
        )
        return
    module.main()
    _phase("completed", module_name)


if __name__ == "__main__":
    main()
