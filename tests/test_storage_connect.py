from pathlib import Path

from agente_bolsa.storage import Store


def test_store_creates_database_directory_only_on_first_connect(tmp_path, monkeypatch):
    database_path = tmp_path / "nested" / "state" / "test.sqlite3"
    store = Store(database_path, tmp_path / "agent_logs")

    assert database_path.parent.exists() is False

    original_mkdir = Path.mkdir
    database_mkdir_calls = []

    def tracked_mkdir(path, *args, **kwargs):
        if path == database_path.parent and kwargs.get("parents") is True:
            database_mkdir_calls.append(path)
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", tracked_mkdir)

    with store.connect():
        pass
    with store.connect():
        pass

    assert database_path.exists() is True
    assert database_mkdir_calls == [database_path.parent]
