from types import SimpleNamespace

from agente_bolsa import cycle_runner as cr
from agente_bolsa.config import Settings


def test_blocked_policy_removes_prebuilt_buys_and_keeps_sells(tmp_path, monkeypatch):
    settings=Settings(_env_file=None, DATA_DIR=str(tmp_path))
    monkeypatch.setattr(cr, '_effective_daily_buy_limit', lambda *a: 0)
    monkeypatch.setattr(cr, 'load_capital_allocation_policy', lambda *a: {'status':'blocked'})
    buy=SimpleNamespace(side='buy',symbol='AAPL',recommendation=None)
    sell=SimpleNamespace(side='sell',symbol='MSFT',recommendation=None)
    reporter=SimpleNamespace(emit=lambda *a,**kw:None)
    rejected=[]
    result=cr._apply_daily_buy_limit(settings, None, reporter, 'cycle', [buy,sell], rejected=rejected)
    assert result==[sell]
    assert len(rejected)==1 and rejected[0]['symbol']=='AAPL'


def test_shadow_retains_legacy_zero_limit_behavior(tmp_path, monkeypatch):
    settings=Settings(_env_file=None, DATA_DIR=str(tmp_path))
    monkeypatch.setattr(cr, '_effective_daily_buy_limit', lambda *a: 0)
    monkeypatch.setattr(cr, 'load_capital_allocation_policy', lambda *a: {'status':'shadow'})
    plans=[SimpleNamespace(side='buy',symbol='AAPL')]
    assert cr._apply_daily_buy_limit(settings,None,None,'cycle',plans) is plans
