"""Synthetic usage accounting contracts; no real transcripts or credentials."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))


def receipt(**extra):
    return dict(schema_version=1,kind='dispatch-run-receipt',dispatch_id='dispatch-a',attempt_id='attempt-a',
        backend='claude',model='claude-test',effort='high',outcome='completed',usage_status='complete',
        usage_basis='claude-input-excludes-cache',tokens_in=10,tokens_cached_in=20,
        tokens_cache_write_in=30,tokens_out=5,**extra)


def assistant(mid='message-a', **usage):
    return dict(type='assistant',sessionId='session-a',requestId='request-'+mid,
        message=dict(id=mid,model='claude-test',content=[dict(type='text',text='PRIVATE BODY MUST NOT APPEAR')],
            usage=dict(input_tokens=10,cache_read_input_tokens=20,cache_creation_input_tokens=30,
                output_tokens=5,**usage)))


def source(fmt,path,selector):
    return dict(source_id=path,format=fmt,path=path+'.jsonl',selector=selector)


def invocation(sources,ident='call-a',**kw):
    return dict(id=ident,pass_id='blind-a',role='reviewer',sources=sources,**kw)


def run(tmp_path,invocations,files,**kw):
    assert (ROOT/'scripts/review_token_ledger.py').exists(),'token ledger missing'
    from review_token_ledger import build_ledger
    for name,rows in files.items():
        (tmp_path/(name+'.jsonl')).write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
    manifest=dict(schema_version=1,review_run_id='review-a',invocations=invocations)
    return build_ledger(manifest,tmp_path,**kw)


def field(report,name,call=0):
    return report['invocations'][call]['usage'][name]


def test_receipt_cache_categories_and_requested_identity(tmp_path):
    s=source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a'))
    report,code=run(tmp_path,[invocation([s])],{'r':[receipt()]})
    assert code==0
    assert field(report,'input_uncached')['value']==10
    assert field(report,'input_total')==dict(value=60,quality='derived',complete=True)
    row=report['invocations'][0]
    assert row['requested_model']=='claude-test' and row['actual_model'] is None
    assert row['requested_effort']=='high' and row['actual_effort'] is None
    assert report['totals']['input_total']['known_subtotal']==60
    assert report['coverage_basis']=='manifest_declared' and report['unlisted_related_receipts'] is None


def test_last_message_record_wins_even_decreasing_or_missing(tmp_path):
    last=assistant(); last['message']['usage']=dict(input_tokens=3,output_tokens=2)
    s=source('claude-assistant-v1','t',dict(session_id='session-a',message_ids=['message-a']))
    report,code=run(tmp_path,[invocation([s])],{'t':[assistant(),last]})
    assert code==1 and field(report,'input_uncached')['value']==3
    assert field(report,'cache_read')['value'] is None and field(report,'output')['value']==2
    assert 'PRIVATE BODY' not in json.dumps(report)


def test_message_ids_and_request_fallback_deduplicate(tmp_path):
    first=assistant(); last=assistant(); last['message'].pop('id')
    s=source('claude-assistant-v1','t',dict(session_id='session-a',message_ids=['message-a']))
    report,code=run(tmp_path,[invocation([s])],{'t':[first,last]})
    assert code==0 and field(report,'input_total')['value']==60


def test_conflicting_message_request_mapping_prevents_exact_total(tmp_path):
    one,two=assistant('a'),assistant('b'); two['requestId']=one['requestId']
    s=source('claude-assistant-v1','t',dict(session_id='session-a',message_ids=['a','b']))
    report,code=run(tmp_path,[invocation([s])],{'t':[one,two]})
    assert code==1 and 'message_identity_conflict' in report['invocations'][0]['reasons']


def test_duplicate_receipts_and_alternative_views_not_added(tmp_path):
    r=source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a'))
    r['provider_session_id']='session-a'
    t=source('claude-assistant-v1','t',dict(session_id='session-a',message_ids=['message-a']))
    report,code=run(tmp_path,[invocation([r,t])],{'r':[receipt(),receipt()],'t':[assistant()]})
    assert code==0 and field(report,'input_total')['value']==60
    assert report['totals']['input_total']['known_subtotal']==60


def test_n4_conflicts_only_compare_observed_values(tmp_path):
    r=receipt(); r.pop('tokens_cached_in'); r['usage_status']='partial'
    ss=[source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a')),
        source('claude-assistant-v1','t',dict(session_id='session-a',message_ids=['message-a']))]
    ss[0]['provider_session_id']='session-a'
    report,code=run(tmp_path,[invocation(ss)],{'r':[r],'t':[assistant()]})
    assert code==0 and field(report,'cache_read')['value']==20
    assert report['invocations'][0]['sources'][0]['usage_status']=='partial'
    r['tokens_out']=7
    report,code=run(tmp_path,[invocation(ss)],{'r':[r],'t':[assistant()]})
    assert code==1 and field(report,'output')['value'] is None
    assert report['totals']['output']['conflicted_invocations']==1


@pytest.mark.parametrize('status',['partial','unavailable',None,'bogus'])
def test_status_never_becomes_complete_zero(tmp_path,status):
    r=receipt(); r['usage_status']=status
    s=source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a'))
    report,code=run(tmp_path,[invocation([s])],{'r':[r]})
    assert code==1 and not report['totals']['output']['complete']
    if status=='unavailable':
        assert field(report,'output')['value'] is None


def test_legacy_claude_zero_requires_provider_evidence(tmp_path):
    r=receipt(); r['tokens_cached_in']=0
    s=source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a'))
    report,code=run(tmp_path,[invocation([s])],{'r':[r]})
    assert code==1 and field(report,'cache_read')['value'] is None


def test_failed_discarded_attempts_still_count(tmp_path):
    r1,r2=receipt(),receipt(); r1['outcome']='failed'; r2.update(attempt_id='attempt-b',outcome='discarded')
    calls=[invocation([source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a',attempt_id=a))],ident=i)
        for a,i in [('attempt-a','one'),('attempt-b','two')]]
    report,code=run(tmp_path,calls,{'r':[r1,r2]})
    assert code==0 and report['totals']['input_total']['known_subtotal']==120


def test_overlapping_invocations_not_double_counted(tmp_path):
    s=source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a'))
    report,code=run(tmp_path,[invocation([s],'one'),invocation([s],'two')],{'r':[receipt()]})
    assert code==1 and report['totals']['input_total']['known_subtotal']==0
    assert all('overlapping_invocations' in c['reasons'] for c in report['invocations'])


def test_codex_single_turn_basis_and_negative_subtraction(tmp_path):
    events=[dict(type='thread.started',thread_id='session-a'),dict(type='turn.completed',
        usage=dict(input_tokens=100,cached_input_tokens=30,cache_write_input_tokens=0,output_tokens=4))]
    s=source('codex-events-v1','c',dict(session_id='session-a',record_indices=[1]))
    report,code=run(tmp_path,[invocation([s])],{'c':events})
    assert code==0 and field(report,'input_uncached')['value']==70
    events[1]['usage']['cached_input_tokens']=101
    report,code=run(tmp_path,[invocation([s])],{'c':events})
    assert code==1 and field(report,'input_uncached')['value'] is None
    assert 'cached_exceeds_input' in report['invocations'][0]['reasons']


def test_codex_multi_turn_scope_stays_unknown_in_events_and_receipts(tmp_path):
    fixture=ROOT/'tests/fixtures/review-evidence/usage/codex-two-turns.jsonl'
    events=[json.loads(line) for line in fixture.read_text().splitlines()]
    s=source('codex-events-v1','c',dict(session_id='session-a',record_indices=[1,2]))
    report,code=run(tmp_path,[invocation([s])],{'c':events})
    assert code==1 and field(report,'input_total')['value'] is None
    assert 'usage_scope_unknown' in report['invocations'][0]['reasons']
    r=receipt(); r.update(backend='codex',usage_basis='codex-input-includes-cached',tokens_in=100)
    report,code=run(tmp_path,[invocation([source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a'))])],{'r':[r]})
    assert code==1 and 'usage_scope_unknown' in report['invocations'][0]['reasons']
    assert field(report,'input_total')['value'] is None


def test_cumulative_terminal_is_used_once_and_not_added_to_messages(tmp_path):
    rows=[dict(type='usage.cumulative',schema_version=1,dispatch_id='dispatch-a',invocation_id='inv-a',
        session_id='session-a',sequence=n,input_tokens=v,cache_read_input_tokens=20,cache_creation_input_tokens=30,
        output_tokens=5,terminal=n==2,complete=n==2,model_identity='claude-test') for n,v in [(1,3),(2,10)]]
    sources=[source('claude-cumulative-v1','c',dict(invocation_id='inv-a',dispatch_id='dispatch-a')),
        source('claude-assistant-v1','t',dict(session_id='session-a',message_ids=['message-a']))]
    report,code=run(tmp_path,[invocation(sources)],{'c':rows,'t':[assistant()]})
    assert code==0 and field(report,'input_total')['value']==60


def test_unlisted_related_receipts_are_counted_only_with_selector(tmp_path):
    r1,r2=receipt(),receipt(); r1['thread_id']=r2['thread_id']='synthetic-thread'; r2['dispatch_id']='other'
    s=source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a'))
    s['related_selector']=dict(thread_id='synthetic-thread')
    report,code=run(tmp_path,[invocation([s])],{'r':[r1,r2,r2]})
    assert code==0 and report['unlisted_related_receipts']==1


@pytest.mark.parametrize('selector,fmt',[({},'clavain-receipt-v1'),({},'unsupported-v1')])
def test_missing_selector_or_unknown_adapter_is_unaccounted(tmp_path,selector,fmt):
    report,code=run(tmp_path,[invocation([source(fmt,'r',selector)])],{'r':[receipt()]})
    assert code==1 and field(report,'output')['value'] is None


def test_malformed_partial_capture_preserves_fields_not_completeness(tmp_path):
    assert (ROOT/'scripts/review_token_ledger.py').exists()
    from review_token_ledger import build_ledger
    (tmp_path/'r.jsonl').write_text(json.dumps(receipt())+'\n{"broken":\n')
    manifest=dict(schema_version=1,review_run_id='run',invocations=[invocation([
        source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a'))])])
    report,code=build_ledger(manifest,tmp_path)
    assert code==1 and field(report,'output')['value']==5


def test_explicit_estimates_do_not_become_measurements(tmp_path):
    call=invocation([],estimates=[dict(category='output',value=30,scope='call-a',method='manual-bound')])
    report,code=run(tmp_path,[call],{})
    assert code==1 and field(report,'output')['quality']=='estimated'
    assert report['totals']['output']['known_subtotal']==0
    assert report['totals']['output']['estimated_subtotal']==30


def test_price_cost_is_estimate_with_unknown_models_incomplete(tmp_path):
    s=source('claude-assistant-v1','t',dict(session_id='session-a',message_ids=['message-a']))
    prices=dict(schema_version=1,currency='USD',effective_date='2026-01-01',models={'claude-test':dict(
        input_uncached=1,cache_read=0.1,cache_write_5m=1.25,cache_write_1h=2,output=3)})
    row=assistant(); row['message']['usage']['cache_creation']=dict(ephemeral_5m_input_tokens=0,ephemeral_1h_input_tokens=30)
    report,code=run(tmp_path,[invocation([s])],{'t':[row]},prices=prices)
    assert code==0 and report['estimated_list_cost']['complete']
    assert report['estimated_list_cost']['value']==pytest.approx(0.000087)
    prices['models']={}
    report,code=run(tmp_path,[invocation([s])],{'t':[row]},prices=prices)
    assert code==1 and not report['estimated_list_cost']['complete']


@pytest.mark.parametrize('mutation',[lambda m:m.update(schema_version=2),
    lambda m:m['invocations'].append(m['invocations'][0]),lambda m:m.update(review_run_id='/private/path')])
def test_invalid_manifest_exits_two_without_echoing_input(tmp_path,mutation):
    assert (ROOT/'scripts/review_token_ledger.py').exists()
    from review_token_ledger import build_ledger
    m=dict(schema_version=1,review_run_id='run',invocations=[invocation([])])
    mutation(m)
    report,code=build_ledger(m,tmp_path)
    assert code==2 and '/private/path' not in json.dumps(report)


def test_conflicting_duplicate_receipts_cannot_be_hidden_by_provider(tmp_path):
    first,last=receipt(),receipt(); last['tokens_out']=99
    sources=[source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a')),
        source('claude-assistant-v1','t',dict(session_id='session-a',message_ids=['message-a']))]
    report,code=run(tmp_path,[invocation(sources)],{'r':[first,last],'t':[assistant()]})
    assert code==1 and not report['totals']['output']['complete']
    assert 'duplicate_receipt_conflict' in report['invocations'][0]['reasons']


@pytest.mark.parametrize('bad',[dict(id=['bad']),dict(id='message-a',usage=['bad'])])
def test_malformed_message_identity_or_usage_does_not_crash(tmp_path,bad):
    row=assistant(); row['message'].update(bad)
    s=source('claude-assistant-v1','t',dict(session_id='session-a',message_ids=['message-a']))
    report,code=run(tmp_path,[invocation([s])],{'t':[row]})
    assert code==1 and not report['invocations'][0]['complete']


def test_terminal_result_and_reasoning_ttl_subsets(tmp_path):
    usage=assistant()['message']['usage']
    usage.update(output_tokens_details={'thinking_tokens':2},
        cache_creation=dict(ephemeral_5m_input_tokens=10,ephemeral_1h_input_tokens=20))
    row=dict(type='result',session_id='session-a',usage=usage,is_error=False,result='PRIVATE RESULT BODY')
    s=source('claude-result-v1','t',dict(session_id='session-a',record_indices=[0]))
    report,code=run(tmp_path,[invocation([s])],{'t':[row]})
    assert code==0 and field(report,'reasoning_output')['value']==2
    assert field(report,'cache_write_5m')['value']==10 and field(report,'output')['value']==5
    assert 'PRIVATE RESULT' not in json.dumps(report)
    usage['output_tokens_details']['thinking_tokens']=6
    report,code=run(tmp_path,[invocation([s])],{'t':[row]})
    assert code==1 and 'invalid_reasoning_subset' in report['invocations'][0]['reasons']


def test_cumulative_counter_reset_is_not_a_second_charge(tmp_path):
    rows=[dict(type='usage.cumulative',schema_version=1,dispatch_id='d',invocation_id='i',session_id='s',
        sequence=n,input_tokens=value,cache_read_input_tokens=2,cache_creation_input_tokens=3,
        output_tokens=5,terminal=n==2,complete=n==2) for n,value in [(1,50),(2,10)]]
    s=source('claude-cumulative-v1','c',dict(dispatch_id='d',invocation_id='i'))
    report,code=run(tmp_path,[invocation([s])],{'c':rows})
    assert code==1 and field(report,'input_uncached')['value']==10
    assert 'cumulative_counter_regression' in report['invocations'][0]['reasons']


def test_related_unidentifiable_receipt_does_not_claim_zero_unlisted(tmp_path):
    one,two=receipt(),receipt(); one['thread_id']=two['thread_id']='related'; two.pop('attempt_id')
    s=source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a',attempt_id='attempt-a'))
    s['related_selector']=dict(thread_id='related')
    report,code=run(tmp_path,[invocation([s])],{'r':[one,two]})
    assert report['unlisted_related_receipts'] is None
    assert code==0 and report['totals']['input_total']['complete']


def test_cli_relative_paths_and_allowlisted_output(tmp_path):
    assert (ROOT/'scripts/review_token_ledger.py').exists()
    row=assistant(); row.update(cwd='/private/transcript/path',error='HIDDEN ERROR',command='HIDDEN COMMAND')
    (tmp_path/'usage.jsonl').write_text(json.dumps(row)+'\n')
    m=dict(schema_version=1,review_run_id='run',invocations=[invocation([
        dict(source_id='source',format='claude-assistant-v1',path='usage.jsonl',selector=dict(session_id='session-a',message_ids=['message-a']))])])
    (tmp_path/'manifest.json').write_text(json.dumps(m))
    proc=subprocess.run([sys.executable,str(ROOT/'scripts/review_token_ledger.py'),'--manifest',str(tmp_path/'manifest.json'),'--json'],capture_output=True,text=True)
    assert proc.returncode==0
    report=json.loads(proc.stdout)
    assert report['totals']['input_total']['known_subtotal']==60
    assert all(s not in proc.stdout for s in ('PRIVATE BODY','/private/','HIDDEN ERROR','HIDDEN COMMAND','usage.jsonl'))


def test_unsupported_selector_is_not_silently_ignored(tmp_path):
    s=source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a',since_timestamp='unknown'))
    report,code=run(tmp_path,[invocation([s])],{'r':[receipt()]})
    assert code==1 and 'selector_unsupported' in report['invocations'][0]['reasons']


def test_cumulative_model_change_and_parent_scope_are_not_exact(tmp_path):
    rows=[dict(type='usage.cumulative',schema_version=1,dispatch_id='d',invocation_id='i',session_id='s',
        model_identity=mod,sequence=n,input_tokens=10,cache_read_input_tokens=2,cache_creation_input_tokens=3,
        output_tokens=5,terminal=n==2,complete=n==2) for n,mod in [(1,'claude-one'),(2,'claude-two')]]
    s=source('claude-cumulative-v1','c',dict(dispatch_id='d',invocation_id='i'))
    report,code=run(tmp_path,[invocation([s])],{'c':rows})
    assert code==1 and 'model_identity_conflict' in report['invocations'][0]['reasons']
    r=receipt(); r['parent_tool_use_id']='parent'
    report,code=run(tmp_path,[invocation([source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a'))])],{'r':[r]})
    assert code==1 and 'parent_scope_unknown' in report['invocations'][0]['reasons']


@pytest.mark.parametrize('bad',[-1,True,'not a count'])
def test_malformed_counts_remain_unknown(tmp_path,bad):
    row=assistant(); row['message']['usage']['output_tokens']=bad
    s=source('claude-assistant-v1','t',dict(session_id='session-a',message_ids=['message-a']))
    report,code=run(tmp_path,[invocation([s])],{'t':[row]})
    assert code==1 and field(report,'output')['value'] is None


def test_no_autodiscovery_and_manifest_relative_totals(tmp_path):
    s=source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a'))
    report,code=run(tmp_path,[invocation([s])],{'r':[receipt()],'not-listed':[receipt()]})
    assert code==0 and report['declared_invocations']==1
    assert report['unlisted_related_receipts'] is None
    assert report['totals']['output']['complete'] and report['totals']['output']['known_subtotal']==5


def test_snapshot_cumulative_replay_and_ttl_price_coverage(tmp_path):
    row=dict(type='usage.cumulative',schema_version=1,dispatch_id='d',invocation_id='i',session_id='s',
        sequence=1,input_tokens=10,cache_read_input_tokens=20,cache_creation_input_tokens=30,
        cache_creation=dict(ephemeral_5m_input_tokens=10,ephemeral_1h_input_tokens=20),
        output_tokens=5,terminal=True,complete=True,model_identity='claude-test')
    s=source('claude-cumulative-v1','c',dict(dispatch_id='d',invocation_id='i'))
    prices=dict(schema_version=1,currency='USD',effective_date='2026-01-01',models={'claude-test':dict(
        input_uncached=1,cache_read=0.1,cache_write_5m=1.25,cache_write_1h=2,output=3)})
    report,code=run(tmp_path,[invocation([s])],{'c':[row,row]},prices=prices)
    assert code==0 and field(report,'input_total')['value']==60
    assert report['estimated_list_cost']['value']==pytest.approx(0.0000795)
    row.pop('cache_creation')
    report,code=run(tmp_path,[invocation([s])],{'c':[row]},prices=prices)
    assert code==1 and not report['estimated_list_cost']['complete']


def test_runnable_synthetic_manifest_fixture():
    path=ROOT/'tests/fixtures/review-evidence/usage/manifest.json'
    proc=subprocess.run([sys.executable,str(ROOT/'scripts/review_token_ledger.py'),'--manifest',str(path),'--json'],capture_output=True,text=True)
    assert proc.returncode==0
    report=json.loads(proc.stdout)
    assert report['totals']['input_total']['known_subtotal']==60


def test_selecting_one_codex_record_cannot_hide_multiturn_scope(tmp_path):
    fixture=ROOT/'tests/fixtures/review-evidence/usage/codex-two-turns.jsonl'
    events=[json.loads(line) for line in fixture.read_text().splitlines()]
    events[2]['usage']['cache_write_input_tokens']=0
    s=source('codex-events-v1','c',dict(session_id='session-a',record_indices=[2]))
    report,code=run(tmp_path,[invocation([s])],{'c':events})
    assert code==1 and field(report,'input_total')['value'] is None
    assert 'usage_scope_unknown' in report['invocations'][0]['reasons']


def test_raw_observations_keep_native_count_names(tmp_path):
    s=source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a'))
    report,code=run(tmp_path,[invocation([s])],{'r':[receipt()]})
    assert code==0
    raw=report['invocations'][0]['sources'][0]['raw_counts'][0]
    assert raw['tokens_in']==10 and raw['tokens_cached_in']==20
    assert 'input_uncached' not in raw


@pytest.mark.parametrize('tail',[
    [dict(type='turn.started')],
    [dict(type='turn.started'),dict(type='turn.failed',error={'message':'PRIVATE ERROR'})],
    [dict(type='error',message='PRIVATE ERROR')],
    [dict(type='thread.started',thread_id='session-a'),dict(type='turn.started'),dict(type='turn.failed')]])
def test_review_p1_started_failed_or_error_turn_cannot_hide_scope(tmp_path,tail):
    events=[dict(type='thread.started',thread_id='session-a'),dict(type='turn.started'),
        dict(type='turn.completed',usage=dict(input_tokens=100,cached_input_tokens=30,
            cache_write_input_tokens=0,output_tokens=4))]+tail
    s=source('codex-events-v1','c',dict(session_id='session-a',record_indices=[2]))
    report,code=run(tmp_path,[invocation([s])],{'c':events})
    assert code==1 and 'usage_scope_unknown' in report['invocations'][0]['reasons']
    assert field(report,'input_total')['value'] is None
    assert not report['totals']['output']['complete'] and 'PRIVATE ERROR' not in json.dumps(report)


def test_review_p1_later_start_is_unknown_even_without_initial_start_record(tmp_path):
    events=[dict(type='thread.started',thread_id='session-a'),dict(type='turn.completed',
        usage=dict(input_tokens=100,cached_input_tokens=30,cache_write_input_tokens=0,output_tokens=4)),dict(type='turn.started')]
    s=source('codex-events-v1','c',dict(session_id='session-a',record_indices=[1]))
    report,code=run(tmp_path,[invocation([s])],{'c':events})
    assert code==1 and field(report,'output')['value'] is None
    assert 'usage_scope_unknown' in report['invocations'][0]['reasons']


@pytest.mark.parametrize('optional',[
    dict(output_tokens_details=dict(thinking_tokens=-3)),
    dict(cache_creation=dict(ephemeral_5m_input_tokens=True)),
    dict(output_tokens='bad')])
def test_review_p2_1_invalid_message_counts_have_diagnostic(tmp_path,optional):
    row=assistant(); row['message']['usage'].update(optional)
    s=source('claude-assistant-v1','t',dict(session_id='session-a',message_ids=['message-a']))
    report,code=run(tmp_path,[invocation([s])],{'t':[row]})
    assert code==1 and 'invalid_count' in report['invocations'][0]['reasons']
    assert report['invocations'][0]['sources'][0]['usage_status']=='partial'


def test_review_p2_2_requested_identity_and_lifecycle_conflicts(tmp_path):
    r=source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a')); r['provider_session_id']='session-a'
    c=source('claude-cumulative-v1','c',dict(dispatch_id='dispatch-a',invocation_id='inv-a'))
    record=dict(type='usage.cumulative',schema_version=1,dispatch_id='dispatch-a',invocation_id='inv-a',
        session_id='session-a',requested_identity='claude-other',status='failed',sequence=1,
        input_tokens=10,cache_read_input_tokens=20,cache_creation_input_tokens=30,output_tokens=5,terminal=True,complete=True)
    report,code=run(tmp_path,[invocation([r,c])],{'r':[receipt()],'c':[record]})
    row=report['invocations'][0]
    assert code==1 and row['requested_model'] is None and row['lifecycle']=='unknown'
    assert {'requested_model_conflict','lifecycle_conflict'}<=set(row['reasons'])
    assert not report['totals']['output']['complete']


def test_review_p2_3_distinct_attempts_are_not_alternative_views(tmp_path):
    first,last=receipt(),receipt(); last['attempt_id']='attempt-b'
    sources=[source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a',attempt_id=a)) for a in ('attempt-a','attempt-b')]
    sources[1]['source_id']='second'
    report,code=run(tmp_path,[invocation(sources)],{'r':[first,last]})
    assert code==1 and 'multiple_attempts' in report['invocations'][0]['reasons']
    assert not report['totals']['input_total']['complete']


@pytest.mark.parametrize('binding,expected',[(None,'provider_session_binding_missing'),('wrong','provider_session_binding_conflict'),('session-a',None)])
def test_review_p2_3_explicit_provider_binding_ignores_ambient_parent(tmp_path,binding,expected):
    r=receipt(); r['session_id']='ambient-parent'
    s=source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a'))
    if binding is not None:
        s['provider_session_id']=binding
    t=source('claude-assistant-v1','t',dict(session_id='session-a',message_ids=['message-a']))
    report,code=run(tmp_path,[invocation([s,t])],{'r':[r],'t':[assistant()]})
    assert code==(1 if expected else 0)
    if expected:
        assert expected in report['invocations'][0]['reasons']
    assert 'ambient-parent' not in json.dumps(report)


def test_review_p2_3_shared_parent_is_not_attempt_identity(tmp_path):
    first,last=receipt(),receipt(); last['attempt_id']='attempt-b'
    first['session_id']=last['session_id']='same-parent'
    calls=[invocation([source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a',attempt_id=a))],ident=i)
        for a,i in [('attempt-a','one'),('attempt-b','two')]]
    report,code=run(tmp_path,calls,{'r':[first,last]})
    assert code==0 and report['totals']['input_total']['known_subtotal']==120


@pytest.mark.parametrize('binding,reason',[(None,'unresolved_overlap'),('session-a','overlapping_invocations')])
def test_review_p2_4_cross_kind_overlap_cannot_double_charge(tmp_path,binding,reason):
    r=receipt(); r['session_id']='ambient-parent'
    s=source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a'))
    if binding:
        s['provider_session_id']=binding
    t=source('claude-assistant-v1','t',dict(session_id='session-a',message_ids=['message-a']))
    report,code=run(tmp_path,[invocation([s],'receipt-view'),invocation([t],'provider-view')],{'r':[r],'t':[assistant()]})
    assert code==1 and report['totals']['input_total']['known_subtotal']==0
    assert all(reason in row['reasons'] for row in report['invocations'])


@pytest.mark.parametrize('backend',[None,'unknown','claude'])
def test_review_p2_5_codex_basis_keeps_receipt_scope_unknown(tmp_path,backend):
    r=receipt(); r.update(backend=backend,usage_basis='codex-input-includes-cached',tokens_in=100)
    report,code=run(tmp_path,[invocation([source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a'))])],{'r':[r]})
    assert code==1 and field(report,'input_total')['value'] is None
    assert 'usage_scope_unknown' in report['invocations'][0]['reasons']


@pytest.mark.parametrize('ttl_rate',[2,None])
def test_review_p2_6_cache_writes_require_ttl_rates(tmp_path,ttl_rate):
    row=assistant(); row['message']['usage']['cache_creation']=dict(ephemeral_5m_input_tokens=0,ephemeral_1h_input_tokens=30)
    rates=dict(input_uncached=1,cache_read=.1,output=3,cache_write=1.25,cache_write_5m=1.25)
    if ttl_rate is not None:
        rates['cache_write_1h']=ttl_rate
    prices=dict(schema_version=1,currency='USD',effective_date='2026-01-01',models={'claude-test':rates})
    s=source('claude-assistant-v1','t',dict(session_id='session-a',message_ids=['message-a']))
    report,code=run(tmp_path,[invocation([s])],{'t':[row]},prices=prices)
    assert code==(0 if ttl_rate else 1)
    if ttl_rate:
        assert report['estimated_list_cost']['value']==pytest.approx(0.000087)
    else:
        assert not report['estimated_list_cost']['complete']


def test_review_bound_disjoint_provider_sessions_can_be_added(tmp_path):
    calls=[]; receipts=[]; messages=[]
    for suffix in ('a','b'):
        r=receipt(); r.update(attempt_id='attempt-'+suffix,session_id='shared-parent')
        receipts.append(r)
        message=assistant('message-'+suffix); message['sessionId']='session-'+suffix
        messages.append(message)
        rs=source('clavain-receipt-v1','r',dict(dispatch_id='dispatch-a',attempt_id='attempt-'+suffix))
        rs['provider_session_id']='session-'+suffix
        ts=source('claude-assistant-v1','t',dict(session_id='session-'+suffix,message_ids=['message-'+suffix]))
        calls.append(invocation([rs,ts],ident='call-'+suffix))
    report,code=run(tmp_path,calls,{'r':receipts,'t':messages})
    assert code==0 and report['totals']['input_total']['known_subtotal']==120


def test_review_invalid_required_count_in_distinct_messages_has_reason(tmp_path):
    first,last=assistant('one'),assistant('two'); last['message']['usage']['output_tokens']=-1
    s=source('claude-assistant-v1','t',dict(session_id='session-a',message_ids=['one','two']))
    report,code=run(tmp_path,[invocation([s])],{'t':[first,last]})
    assert code==1 and field(report,'output')['value'] is None
    assert 'invalid_count' in report['invocations'][0]['reasons']
