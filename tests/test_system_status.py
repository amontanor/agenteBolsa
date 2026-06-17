from agente_bolsa.tools.system_status import DOWN, OK, WARN, _global_verdict, _waiting_after_scheduler_restart


def test_waiting_after_scheduler_restart_hides_stale_first_run():
    assert _waiting_after_scheduler_restart(job_age_min=600.0, scheduler_age_min=0.5, cadence_min=15.0)


def test_waiting_after_scheduler_restart_expires_after_cadence_grace():
    assert not _waiting_after_scheduler_restart(job_age_min=600.0, scheduler_age_min=18.0, cadence_min=15.0)


def test_waiting_after_scheduler_restart_does_not_hide_fresh_job():
    assert not _waiting_after_scheduler_restart(job_age_min=5.0, scheduler_age_min=0.5, cadence_min=15.0)


def test_global_verdict_warns_on_non_critical_down():
    components = [
        {"name": "Scheduler", "state": OK},
        {"name": "Ciclo de mercado (15m)", "state": OK},
        {"name": "LLM de decision", "state": OK},
        {"name": "Base de datos", "state": DOWN},
    ]

    assert _global_verdict(components) == WARN


def test_global_verdict_down_on_critical_down():
    components = [
        {"name": "Scheduler", "state": DOWN},
        {"name": "Base de datos", "state": OK},
    ]

    assert _global_verdict(components) == DOWN
