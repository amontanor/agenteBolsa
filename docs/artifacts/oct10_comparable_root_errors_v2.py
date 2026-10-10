"""Independent bounded comparison, exact baseline AST, local data only."""
import ast,copy,hashlib,json,socket,subprocess,sys
from pathlib import Path
from contextlib import contextmanager
ROOT=Path('C:/Users/utopi/.codex/worktrees/bolsa-controls-memory-oct10/agenteBolsa')
BASE='43325d7b8c6525fa3665537f5109d570f2f2f5a9'
def forbidden(*a,**kw):raise RuntimeError('external_provider_forbidden')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=forbidden
from agente_bolsa.tools import comparable_controls as m
raw=subprocess.check_output(['git','show',BASE+':src/agente_bolsa/tools/comparable_controls.py'],cwd=ROOT)
node=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='build_comparable_control_quality')
namespace=dict(m.__dict__)
exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<exact-comparable-base>','exec'),namespace)
old=namespace[node.name]
def cs(**kw):
 x={'schema_version':m.SCHEMA_VERSION,'status':'verified','treatment':{'signal_id':'t'},'controls':[{'signal_id':'c'}]};x.update(kw);return x
def rec(x):return {'created_at':'2026-10-09','payload':{'comparable_control_set':x}}
def out(i,x):return {'signal_id':i,'outcome':x}
class Store:
 def __init__(self,r,o):self.r=copy.deepcopy(r);self.o=copy.deepcopy(o);self.reads=[]
 def trade_recommendations(self,**kw):self.reads.append(['recommendations',kw]);return self.r
 def signal_outcomes(self,**kw):self.reads.append(['outcomes',kw]);return self.o
class Streaming(Store):
 @contextmanager
 def comparable_control_quality_record_stream(self,*,batch_size):
  def records():
   yield from (('recommendation',r) for r in self.trade_recommendations(limit=50000))
   yield from (('outcome',o) for o in self.signal_outcomes(limit=200000,include_lab_book=True,include_learning_experiment=True))
  gen=records()
  try:yield gen
  finally:gen.close()
def run(f,s):
 try:result={'result':f(s)}
 except Exception as e:result={'error_type':type(e).__name__,'error':str(e)}
 result['reads']=s.reads
 return result
cases=[
 ('valid',[rec(cs())],[out('t',{'matured_horizons':{'10d':True}})]),
 ('invalid_overwritten',[rec(cs())],[out('t',[1]),out('t',{'matured_horizons':{'10d':True}})]),
 ('invalid_horizons_overwritten',[rec(cs())],[out('t',{'matured_horizons':[1]}),out('t',{})]),
 ('invalid_final',[rec(cs())],[out('t',{}),out('t',[1])]),
 ('irrelevant_invalid',[rec(cs())],[out('unused',[1])]),
 ('verified_controls_scalar',[rec(cs(controls=1))],[]),
 ('identity_then_later_outcome',[rec(cs(controls=[1])),rec(cs(treatment={'signal_id':'later'},controls=[]))],[out('later','bad')]),
 ('metric_then_later_maturity',[rec(cs(eligible_controls_omitted='bad')),rec(cs(treatment={'signal_id':'later'},controls=[]))],[out('later',[1])]),
 ('fields_across_records',[rec(cs(eligible_controls_omitted='bad')),rec(cs(blocked_candidates=1))],[]),
 ('partial_controls_scalar',[rec(cs(status='partially_comparable',controls=1))],[]),
 ('invalid_verified_controls_before_later_recommendation',[rec(cs(controls=1)),{'payload':[1]}],[]),
 ('invalid_partial_controls_before_later_recommendation',[rec(cs(status='partially_comparable',controls=1)),{'payload':[1]}],[]),
 ('invalid_recommendation_after_metric',[rec(cs(eligible_controls_omitted='bad')),{'payload':[1]}],[])
]
result={'base':BASE,'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'source_sha256':hashlib.sha256((ROOT/'src/agente_bolsa/tools/comparable_controls.py').read_bytes()).hexdigest(),'base_blob_sha256':hashlib.sha256(raw).hexdigest(),'cases':[]}
for name,r,o in cases:
 a=run(old,Store(r,o));b=run(m.build_comparable_control_quality,Streaming(r,o))
 result['cases'].append({'name':name,'equal':a==b,'base':a,'candidate':b})
result['all_equal']=all(x['equal'] for x in result['cases'])
path=Path('C:/Users/utopi/.codex/worktrees/ef99/agenteBolsa/audit_oct10_comparable_root_errors_v2.json')
with path.open('x',encoding='utf-8') as fp:json.dump(result,fp,indent=2)
print(json.dumps({'all_equal':result['all_equal'],'cases':[{'name':x['name'],'equal':x['equal'],'base_error':x['base'].get('error'),'candidate_error':x['candidate'].get('error')} for x in result['cases']]}))

