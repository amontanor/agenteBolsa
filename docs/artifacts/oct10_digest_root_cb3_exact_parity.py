"""Read-only baseline code, temporary fixtures, no external providers."""
import ast,contextlib,gc,hashlib,io,json,logging,os,socket,subprocess,sys,tempfile
from pathlib import Path
from datetime import datetime as RealDatetime,date as RealDate,timezone
root=Path('C:/Users/utopi/.codex/worktrees/bolsa-digest-oct10/agenteBolsa')
base='cb3d8805a9890fab0357b0ba3a3f7afaa8577586'
raw=subprocess.check_output(['git','show',base+':src/agente_bolsa/main.py'],cwd=root)
node=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='command_continuous_improvement_lab')
def forbidden(*a,**k):raise RuntimeError('external_provider_forbidden_in_baseline_comparison')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=forbidden
fixed=RealDatetime(2026,10,10,9,tzinfo=timezone.utc)
class FrozenDatetime(RealDatetime):
 @classmethod
 def now(cls,tz=None):return fixed.replace(tzinfo=None) if tz is None else fixed.astimezone(tz)
 @classmethod
 def utcnow(cls):return fixed.replace(tzinfo=None)
 @classmethod
 def today(cls):return fixed.replace(tzinfo=None)
class FrozenDate(RealDate):
 @classmethod
 def today(cls):return fixed.date()
result={'base':base,'base_main_sha256':hashlib.sha256(raw).hexdigest(),'mode':'execute_exact_baseline_AST_not_product_code','cases':[]}
with tempfile.TemporaryDirectory(prefix='bolsa-cb3-digest-parity-') as directory:
 os.environ.update(DATA_DIR=directory,TRADING_MODE='paper',ALPACA_PAPER='true',ALLOW_LIVE_TRADING='false',ALLOW_AUTO_APPLY_IMPROVEMENTS='false')
 from agente_bolsa.config import Settings
 from agente_bolsa.storage import Store
 import agente_bolsa.main as current
 import agente_bolsa.digest_cli as light
 from agente_bolsa.continuous_improvement.digest import build_lab_digest,format_lab_digest_text
 from agente_bolsa.tools.config_audit import digest_safety_summary
 from agente_bolsa.continuous_improvement import ContinuousImprovementOrchestrator
 from agente_bolsa.continuous_improvement.orchestrator import ContinuousImprovementOrchestrator as direct
 assert ContinuousImprovementOrchestrator is direct
 for module in list(sys.modules.values()):
  if module is None or not getattr(module,'__name__','').startswith('agente_bolsa.'):continue
  if getattr(module,'datetime',None) is RealDatetime:module.datetime=FrozenDatetime
  if getattr(module,'date',None) is RealDate:module.date=FrozenDate
 settings=Settings(_env_file=None,DATA_DIR=Path(directory),TRADING_MODE='paper',ALPACA_PAPER=True,ALLOW_LIVE_TRADING=False,ALLOW_AUTO_APPLY_IMPROVEMENTS=False)
 settings.ensure_runtime_dirs()
 current.get_settings=lambda:settings
 current.configure_logging=lambda *a,**k:None
 legacy_stores=[]
 def legacy_store(*args,**kwargs):
  instance=Store(*args,**kwargs);legacy_stores.append(instance);return instance
 space=dict(current.__dict__)
 space['Store']=legacy_store
 space.update(build_lab_digest=build_lab_digest,format_lab_digest_text=format_lab_digest_text,digest_safety_summary=digest_safety_summary)
 exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<cb3-exact-digest-command>','exec'),space)
 old=space['command_continuous_improvement_lab']
 for populated in (False,True):
  if populated:
   st=Store(settings.database_path,settings.agent_logs_dir)
   try:
    st.ensure_schema()
    st.save_trade_recommendation(recommendation_id='baseline-fixture',cycle_id='fixture-cycle',symbol='SYNTH',action='hold',confidence=.75,payload={'fixture':True,'source':'isolated_baseline'})
   finally:st.close_read_connection()
  for use_out in (False,True):
   for as_json in (False,True):
    target=Path(directory)/'reports'/'same-output.md'
    args=type('Args',(),{'lab_command':'digest','days':3,'out':str(target) if use_out else None,'json':as_json})()
    legacy_output=io.StringIO()
    with contextlib.redirect_stdout(legacy_output):old(args)
    legacy_file=target.read_text(encoding='utf-8') if use_out else None
    # Legacy keeps its read handle open; cleanup belongs to this harness only.
    for legacy_instance in legacy_stores:legacy_instance.close_read_connection()
    st=Store(settings.database_path,settings.agent_logs_dir)
    st.ensure_schema()
    new_output=io.StringIO()
    with contextlib.redirect_stdout(new_output):light.execute_digest_command(args,settings=settings,store=st)
    new_file=target.read_text(encoding='utf-8') if use_out else None
    first,second=legacy_output.getvalue(),new_output.getvalue()
    if as_json:first,second=json.loads(first),json.loads(second)
    equal=first==second and legacy_file==new_file
    case={'populated':populated,'out':use_out,'json':as_json,'exact_output_equal':first==second,'exact_file_equal':legacy_file==new_file,'normalization':'none'}
    result['cases'].append(case)
    if not equal:raise AssertionError(json.dumps(case))
 result['public_orchestrator_identity_equal']=True
 result['all_equal']=all(c['exact_output_equal'] and c['exact_file_equal'] for c in result['cases'])
 logging.shutdown()
 gc.collect()
output=Path('C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_oct10_digest_cb3_exact_parity_v3.json')
with output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2)
print(json.dumps(result))


