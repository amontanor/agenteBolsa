from __future__ import annotations

from types import SimpleNamespace

from agente_bolsa import main


def test_command_web_does_not_launch_when_port_is_open(monkeypatch, tmp_path, capsys):
    args = SimpleNamespace(host="127.0.0.1", port=8501)
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(logs_dir=tmp_path, log_level="INFO"))
    monkeypatch.setattr(main, "_is_tcp_port_open", lambda host, port: True)

    def fail_run(*_args, **_kwargs):
        raise AssertionError("streamlit should not be launched")

    monkeypatch.setattr(main.subprocess, "run", fail_run)

    main.command_web(args)

    assert "Panel web ya corriendo en http://127.0.0.1:8501" in capsys.readouterr().out


def test_command_web_launches_streamlit_when_port_is_closed(monkeypatch, tmp_path):
    args = SimpleNamespace(host="127.0.0.1", port=8501)
    calls: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(logs_dir=tmp_path, log_level="INFO"))
    monkeypatch.setattr(main, "_is_tcp_port_open", lambda host, port: False)
    managed_python = tmp_path / ".venv" / "Scripts" / "python.exe"
    managed_python.parent.mkdir(parents=True, exist_ok=True)
    managed_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(main, "require_managed_python", lambda: managed_python)
    monkeypatch.setattr(main.subprocess, "run", lambda cmd, check=False: calls.append((cmd, check)))

    main.command_web(args)

    assert calls
    cmd, check = calls[0]
    assert check is False
    assert cmd[:4] == [str(managed_python), "-m", "streamlit", "run"]
    assert "--server.port" in cmd
    assert "8501" in cmd
