from agente_bolsa.tools.system_status import _waiting_after_scheduler_restart


def test_waiting_after_scheduler_restart_hides_stale_first_run():
    assert _waiting_after_scheduler_restart(job_age_min=600.0, scheduler_age_min=0.5, cadence_min=15.0)


def test_waiting_after_scheduler_restart_expires_after_cadence_grace():
    assert not _waiting_after_scheduler_restart(job_age_min=600.0, scheduler_age_min=18.0, cadence_min=15.0)


def test_waiting_after_scheduler_restart_does_not_hide_fresh_job():
    assert not _waiting_after_scheduler_restart(job_age_min=5.0, scheduler_age_min=0.5, cadence_min=15.0)
