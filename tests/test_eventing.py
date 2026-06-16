import builtins

from agente_bolsa.eventing import EventReporter


class _StoreSpy:
    def __init__(self):
        self.events = []

    def record_agent_event(self, event):
        self.events.append(event)


def test_event_reporter_ignores_broken_stdout(monkeypatch):
    store = _StoreSpy()
    reporter = EventReporter(store, verbose=True)

    def broken_print(*args, **kwargs):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(builtins, "print", broken_print)

    reporter.emit(
        "orchestrator",
        "scheduled_market_cycle_check",
        "mkt_test",
        "Comprobando ciclo.",
    )

    assert len(store.events) == 1
    assert store.events[0].event_type == "scheduled_market_cycle_check"
