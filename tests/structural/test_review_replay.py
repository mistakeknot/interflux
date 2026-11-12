"""Synthetic replay contracts and a test-only exhaustive matching oracle."""
import itertools
import json
import sys
import subprocess
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))


def matcher(gold,findings,edges):
    assert (ROOT/'scripts/_review_replay.py').exists(),'replay matcher missing'
    from _review_replay import PriorityMatcher
    return PriorityMatcher(gold,findings,edges)


def assignment(rows):
    return {r['gold_id']:r['finding_id'] for r in rows}


def oracle(gold,findings,edges):
    order=sorted(gold,key=lambda g:(gold[g]!='decision',g))
    results=[]
    def walk(i,used,chosen):
        if i==len(order):
            results.append(dict(chosen)); return
        g=order[i]
        for f in sorted(findings):
            if f not in used and (f,g) in edges:
                walk(i+1,used|{f},dict(chosen,**{g:f}))
        walk(i+1,used,chosen)
    walk(0,set(),{})
    def counts(a):
        return sum(gold[g]=='decision' for g in a),sum(gold[g]=='plain_fix' for g in a)
    optimum=max(map(counts,results))
    best=[a for a in results if counts(a)==optimum]
    key=lambda a:tuple((0,a[g]) if g in a else (1,'') for g in order)
    return results,optimum,min(best,key=key),counts


def test_decision_priority_and_recall_changing_alternative():
    m=matcher({'a-fix':'plain_fix','z-decision':'decision'},['f'],[('f','a-fix'),('f','z-decision')])
    result=m.analyze()
    assert assignment(result['matching']['assignment'])=={'z-decision':'f'}
    assert result['matching']['maximum_cardinality']==1
    assert result['ambiguity']['recall_alternatives'][0]['decision_matches']==0
    assert result['ambiguity']['recall_alternatives'][0]['plain_fix_matches']==1


def test_augmenting_reassignment_preserves_decision_and_adds_fix():
    m=matcher({'d':'decision','p':'plain_fix'},['a','b'],[('a','d'),('b','d'),('a','p')])
    result=m.analyze()
    assert assignment(result['matching']['assignment'])=={'d':'b','p':'a'}
    assert (result['matching']['decision_matches'],result['matching']['plain_fix_matches'])==(1,1)
    assert m.feasible(1,1,{('a','d')},set()) is None
    assert m.feasible(-1,0,set(),set()) is None
    assert m.feasible(1,0,{('not-found','d')},set()) is None


def test_per_gold_unmatched_possibility_and_occurrence_ambiguity():
    m=matcher({'a':'decision','b':'decision'},['f'],[('f','a'),('f','b')])
    result=m.analyze()
    assert all(g['unmatched_possible'] and g['occurrence_ambiguous'] for g in result['ambiguity']['per_gold'])
    assert len(result['ambiguity']['priority_alternatives'])==1
    witness=result['ambiguity']['priority_alternatives'][0]
    assert assignment(witness['assignment'])=={'b':'f'}
    assert len(witness['changed_gold_assignments'])==2
    # Forbidding ALL incident edges, not testing just one edge, proves unmatched.
    assert m.feasible(1,0,set(),{('f','a')}) is not None


def test_permutation_and_duplicate_edges_do_not_change_matching():
    gold={'d':'decision','p':'plain_fix'}; findings=['a','b']; edges=list(itertools.product(findings,gold))
    first=matcher(gold,findings,edges).analyze()
    second=matcher(dict(reversed(list(gold.items()))),list(reversed(findings)),list(reversed(edges))+edges).analyze()
    assert first==second
    assert assignment(first['matching']['assignment'])=={'d':'a','p':'b'}


@pytest.mark.parametrize('kinds,findings',[
    ({'a':'decision','b':'decision','c':'plain_fix'},['x','y']),
    ({'a':'decision','b':'plain_fix','c':'plain_fix'},['x','y']),
    ({'a':'decision','b':'plain_fix'},['x','y','z'])])
def test_exhaustive_small_graph_oracle(kinds,findings):
    potential=list(itertools.product(findings,kinds))
    for mask in range(1<<len(potential)):
        edges={edge for i,edge in enumerate(potential) if mask&(1<<i)}
        all_assignments,optimum,canonical,counts=oracle(kinds,findings,edges)
        m=matcher(kinds,findings,edges); result=m.analyze()
        matching=result['matching']; ambiguity=result['ambiguity']
        assert (matching['decision_matches'],matching['plain_fix_matches'])==optimum
        assert assignment(matching['assignment'])==canonical
        k=max(map(len,all_assignments))
        assert matching['maximum_cardinality']==k==sum(optimum)
        best=[a for a in all_assignments if counts(a)==optimum]
        assert {(r['finding_id'],r['gold_id']) for r in ambiguity['edge_membership']}==edges
        for d in range(sum(v=='decision' for v in kinds.values())+1):
            for p in range(sum(v=='plain_fix' for v in kinds.values())+1):
                available=[a for a in all_assignments if counts(a)==(d,p)]
                assert (m.feasible(d,p) is not None)==bool(available)
                for edge in edges:
                    f,g=edge
                    assert (m.feasible(d,p,{edge}) is not None)==any(a.get(g)==f for a in available)
                    assert (m.feasible(d,p,forbidden_edges={edge}) is not None)==any(a.get(g)!=f for a in available)
        for row in ambiguity['edge_membership']:
            f,g=row['finding_id'],row['gold_id']
            assert row['in_some_priority_optimum']==any(a.get(g)==f for a in best)
            assert row['in_some_maximum_cardinality_matching']==any(len(a)==k and a.get(g)==f for a in all_assignments)
        for row in ambiguity['per_gold']:
            options={a.get(row['gold_id']) for a in best}
            assert row['unmatched_possible']==(None in options)
            assert row['occurrence_ambiguous']==(len(options)>1)
        expected={counts(a) for a in all_assignments if len(a)==k}-{optimum}
        assert {(a['decision_matches'],a['plain_fix_matches']) for a in ambiguity['recall_alternatives']}==expected
        for alt in ambiguity['priority_alternatives']:
            a=assignment(alt['assignment'])
            assert a in best and a[alt['forced_edge']['gold_id']]==alt['forced_edge']['finding_id']


def prepare(tmp_path,findings=None,items=None,count=1):
    from markdown_section_index import build_index
    from _review_evidence import canonical_json
    idx=build_index(b'# Alpha\nAlpha prose.\n# Beta\nBeta prose.\n','docs/example.md')
    snapshot={key:idx[key] for key in ('document_id','document_sha256','parser_version','parser_sha256','syntax_profile','index_sha256')}
    sections=[s['section_id'] for s in idx['sections'][1:]]
    if items is None:
        items=[dict(id='g-d',disposition='accepted',kind='decision',sections=[sections[0]],claim='Decision issue.'),
            dict(id='g-p',disposition='accepted',kind='plain_fix',sections=[sections[1]],claim='Plain issue.')]
    if findings is None:
        findings=[dict(id='f',claim='Paraphrase needing external judgment.',location='docs/example.md:2')]
    findings=[dict(row,pass_id='blind-a') if 'pass_id' not in row and 'pass_ids' not in row else row for row in findings]
    (tmp_path/'index.json').write_bytes(canonical_json(idx))
    (tmp_path/'gold.json').write_bytes(canonical_json(dict(schema_version=1,snapshot=snapshot,index='index.json',items=items)))
    runs=[]
    for n in range(count):
        name=f'findings-{n}.jsonl'
        (tmp_path/name).write_text(''.join(json.dumps(row)+'\n' for row in findings))
        runs.append(dict(id=f'run-{n}',snapshot=snapshot,findings=name,input_mode='snapshot',
            stage='post_adjudication',passes=['blind-a'],invocation_ids=['call-a']))
    (tmp_path/'runs.json').write_bytes(canonical_json(dict(schema_version=1,runs=runs)))
    return sections


def evaluate(tmp_path,mode='candidates'):
    assert (ROOT/'scripts/score_review_replay.py').exists(),'scorer CLI missing'
    from score_review_replay import evaluate_files
    return evaluate_files(tmp_path/'gold.json',tmp_path/'runs.json',
        tmp_path/'judgments.json' if mode=='score' and (tmp_path/'judgments.json').exists() else None,mode)


def judgments(tmp_path,report,pairs=(),extras=(),coverage=False):
    records=[]; covers=[]
    for scope in report['runs']:
        if not scope['available']:
            continue
        binding=dict(run_id=scope['run_id'],ablation_id=scope['ablation_id'],inputs_sha256=scope['inputs_sha256'])
        for f,g,verdict in pairs:
            records.append(dict(binding,id=f'j-{len(records)}',type='match',finding_id=f,gold_id=g,verdict=verdict,
                judge=dict(id='human',family='human',kind='human'),reason='Synthetic external judgment.'))
        for f,verdict,family in extras:
            records.append(dict(binding,id=f'j-{len(records)}',type='extra',finding_id=f,verdict=verdict,
                judge=dict(id=family,family=family,kind='human' if family=='human' else 'model'),reason='Synthetic extra judgment.'))
        if coverage:
            covers.append(dict(binding,id=f'coverage-{len(covers)}',type='semantic',complete=True,
                judge=dict(id='human',family='human',kind='human'),reason='Entire finding/gold universe reviewed.'))
    value=dict(schema_version=1,judgments=records,resolutions=[],coverage=covers)
    (tmp_path/'judgments.json').write_text(json.dumps(value))
    return value


def test_same_section_is_candidate_only_and_incomplete_recall(tmp_path):
    prepare(tmp_path)
    report,code=evaluate(tmp_path)
    assert code==0 and report['runs'][0]['candidates']==[dict(finding_id='f',gold_id='g-d',basis='section_overlap')]
    scored,code=evaluate(tmp_path,'score')
    row=scored['runs'][0]
    assert code==1 and row['recall_status']=='confirmed_recall_lower_bound'
    assert row['metrics']['decision_recall']['value']==0
    assert row['unmatched_gold'][0]['status']=='unresolved'
    assert row['extras'][0]['status']=='unverified'


def test_external_nonoverlap_paraphrase_and_separate_recall(tmp_path):
    prepare(tmp_path)
    candidates,_=evaluate(tmp_path)
    judgments(tmp_path,candidates,[('f','g-p','same_issue')],coverage=True)
    report,code=evaluate(tmp_path,'score')
    row=report['runs'][0]
    assert code==0 and row['metrics']['decision_recall']['value']==0
    assert row['metrics']['plain_fix_recall']['value']==1
    assert assignment(row['matching']['assignment'])=={'g-p':'f'}


def test_rejected_and_unlabelled_gold_never_enter_denominator(tmp_path):
    sections=prepare(tmp_path)
    gold=json.loads((tmp_path/'gold.json').read_text())
    gold['items']=[dict(id='rejected',disposition='rejected',kind=None,sections=[sections[0]],claim='Rejected recommendation.'),
        dict(id='unknown',disposition=None,kind='decision',sections=[sections[0]],claim='No ruling.')]
    (tmp_path/'gold.json').write_text(json.dumps(gold))
    candidates,_=evaluate(tmp_path)
    judgments(tmp_path,candidates,[('f','rejected','same_issue')],[('f','valid','human')],True)
    report,code=evaluate(tmp_path,'score')
    row=report['runs'][0]
    assert code==1 and not row['labels_complete']
    assert row['metrics']['decision_recall']['value'] is None
    assert row['rejected_relations'][0]['gold_id']=='rejected'
    assert row['extras'][0]['status']=='valid'


def test_three_family_extras_and_conflicts_need_explicit_resolution(tmp_path):
    prepare(tmp_path,findings=[dict(id='extra',claim='Additional issue.',location='docs/example.md:2')])
    candidates,_=evaluate(tmp_path)
    data=judgments(tmp_path,candidates,extras=[('extra','valid','lab-a')],coverage=True)
    report,code=evaluate(tmp_path,'score')
    assert code==1 and not report['runs'][0]['extras'][0]['three_family_coverage']
    data=judgments(tmp_path,candidates,extras=[('extra','valid',lab) for lab in ('lab-a','lab-b','lab-c')],coverage=True)
    report,code=evaluate(tmp_path,'score')
    assert code==0 and report['runs'][0]['extras'][0]['three_family_coverage']
    data['judgments'][1]['verdict']='invalid'
    (tmp_path/'judgments.json').write_text(json.dumps(data))
    report,code=evaluate(tmp_path,'score')
    assert code==1 and report['runs'][0]['extras'][0]['status']=='uncertain'
    resolution=dict(data['judgments'][0],id='resolution',supersedes=[j['id'] for j in data['judgments']],
        judge=dict(id='human',family='human',kind='human'))
    data['resolutions']=[resolution]
    (tmp_path/'judgments.json').write_text(json.dumps(data))
    report,code=evaluate(tmp_path,'score')
    assert code==0 and len(report['judgments'])==4


@pytest.mark.parametrize('mutation',['claim','snapshot','dangling'])
def test_stale_judgment_binding_or_dangling_ids_invalid(tmp_path,mutation):
    prepare(tmp_path); candidates,_=evaluate(tmp_path)
    data=judgments(tmp_path,candidates,[('f','g-d','same_issue')],coverage=True)
    if mutation=='claim':
        path=tmp_path/'findings-0.jsonl'; row=json.loads(path.read_text()); row['claim']+=' '
        path.write_text(json.dumps(row)+'\n')
    elif mutation=='snapshot':
        data['judgments'][0]['inputs_sha256']='0'*64
        (tmp_path/'judgments.json').write_text(json.dumps(data))
    else:
        data['judgments'][0]['gold_id']='not-present'
        (tmp_path/'judgments.json').write_text(json.dumps(data))
    report,code=evaluate(tmp_path,'score')
    assert code==2 and report['run_status']=='invalid_input'


def test_location_ranges_keep_declared_and_derived_representations(tmp_path):
    sections=prepare(tmp_path)
    row=dict(id='f',claim='Cross-section issue.',location='./docs//example.md:2-4',sections=[sections[0]],pass_id='blind-a')
    (tmp_path/'findings-0.jsonl').write_text(json.dumps(row)+'\n')
    report,code=evaluate(tmp_path)
    finding=report['runs'][0]['findings'][0]
    assert code==0 and finding['derived_sections']==sorted(sections)
    assert finding['declared_sections']==[sections[0]] and 'section_disagreement' in finding['diagnostics']
    assert len(report['runs'][0]['candidates'])==2


@pytest.mark.parametrize('location',['other.md:2','docs/example.md:0','docs/example.md:2-99','unknown'])
def test_invalid_location_does_not_remove_finding_from_external_judgment(tmp_path,location):
    prepare(tmp_path,findings=[dict(id='f',claim='Issue',location=location)])
    candidates,code=evaluate(tmp_path)
    assert code==0 and candidates['runs'][0]['candidates']==[]
    judgments(tmp_path,candidates,[('f','g-d','same_issue')],coverage=True)
    report,code=evaluate(tmp_path,'score')
    assert code==0 and report['runs'][0]['metrics']['decision_recall']['value']==1


def test_runs_and_unavailable_ablations_are_not_pooled(tmp_path):
    prepare(tmp_path,count=3)
    manifest=json.loads((tmp_path/'runs.json').read_text())
    manifest['runs'][0]['ablations']=[dict(id='one-pass',stage='pre_adjudication',passes=['blind-a'])]
    (tmp_path/'runs.json').write_text(json.dumps(manifest))
    candidates,code=evaluate(tmp_path)
    assert code==0 and len(candidates['runs'])==4
    assert not candidates['runs'][1]['available']
    judgments(tmp_path,candidates,[('f','g-d','same_issue')],coverage=True)
    report,code=evaluate(tmp_path,'score')
    assert code==1 and len([r for r in report['runs'] if r['available']])==3
    assert all(r['matching']['decision_matches']==1 for r in report['runs'] if r['available'])


def test_empty_sets_null_denominators_and_zero_runs_rejected(tmp_path):
    prepare(tmp_path,findings=[],items=[])
    report,code=evaluate(tmp_path,'score')
    assert code==0 and report['runs'][0]['metrics']['decision_recall']['value'] is None
    (tmp_path/'runs.json').write_text(json.dumps(dict(schema_version=1,runs=[])))
    assert evaluate(tmp_path)[1]==2


def test_canonical_binding_repeatability_and_quote_invalidation(tmp_path):
    prepare(tmp_path); first,_=evaluate(tmp_path); second,_=evaluate(tmp_path)
    assert first==second
    path=tmp_path/'findings-0.jsonl'; row=json.loads(path.read_text())
    row['quote']=dict(section_id='unknown',text='Exact added evidence.')
    path.write_text(json.dumps(row)+'\n')
    newer,_=evaluate(tmp_path)
    assert newer['runs'][0]['inputs_sha256']!=first['runs'][0]['inputs_sha256']


def test_duplicate_findings_are_extras_with_explicit_ambiguity(tmp_path):
    prepare(tmp_path,findings=[dict(id=f,claim='Same issue.',location='docs/example.md:2') for f in ('a','b')])
    candidates,_=evaluate(tmp_path)
    judgments(tmp_path,candidates,[('a','g-d','same_issue'),('b','g-d','same_issue')],
        [('b','valid','human')],True)
    report,code=evaluate(tmp_path,'score')
    row=report['runs'][0]
    assert code==0 and row['metrics']['decision_recall']['confirmed_matches']==1
    assert row['extras'][0]['finding_id']=='b' and row['extras'][0]['occurrence_ambiguous']
    assert len(row['ambiguity']['priority_alternatives'])==1


def test_missing_gold_labels_suppress_ratio_instead_of_inventing_denominator(tmp_path):
    prepare(tmp_path)
    path=tmp_path/'gold.json'; gold=json.loads(path.read_text())
    gold['items'][1]['kind']=None
    path.write_text(json.dumps(gold))
    candidates,_=evaluate(tmp_path); judgments(tmp_path,candidates,[('f','g-d','same_issue')],coverage=True)
    report,code=evaluate(tmp_path,'score')
    assert code==1 and report['runs'][0]['metrics']['decision_recall']['value'] is None
    assert any(g['id']=='g-p' and not g['eligible'] for g in report['gold_items'])


def test_conflicting_matches_coverage_cannot_override_uncertainty(tmp_path):
    prepare(tmp_path); candidates,_=evaluate(tmp_path)
    data=judgments(tmp_path,candidates,[('f','g-d','same_issue'),('f','g-d','different_issue')],coverage=True)
    report,code=evaluate(tmp_path,'score')
    assert code==1 and report['runs'][0]['matching']['decision_matches']==0
    assert not report['runs'][0]['semantic_coverage_complete']
    resolution=dict(data['judgments'][0],id='resolution',supersedes=['j-0','j-1'])
    data['resolutions']=[resolution]
    (tmp_path/'judgments.json').write_text(json.dumps(data))
    assert evaluate(tmp_path,'score')[1]==0


def test_ablation_requires_separate_artifact_and_distinct_judgment_binding(tmp_path):
    prepare(tmp_path)
    path=tmp_path/'runs.json'; manifest=json.loads(path.read_text()); run=manifest['runs'][0]
    run['ablations']=[dict(id='one-pass',stage='pre_adjudication',passes=['blind-a'],findings=run['findings'])]
    path.write_text(json.dumps(manifest))
    report,code=evaluate(tmp_path)
    assert code==0 and not report['runs'][1]['available']
    (tmp_path/'pre.jsonl').write_bytes((tmp_path/run['findings']).read_bytes())
    run['ablations'][0]['findings']='pre.jsonl'; path.write_text(json.dumps(manifest))
    report,code=evaluate(tmp_path)
    assert code==0 and report['runs'][1]['available']
    assert report['runs'][0]['inputs_sha256']!=report['runs'][1]['inputs_sha256']


def test_cost_requires_matching_run_and_exact_invocation_scope(tmp_path):
    prepare(tmp_path)
    path=tmp_path/'runs.json'; runs=json.loads(path.read_text()); runs['runs'][0]['token_ledger']='usage.json'
    path.write_text(json.dumps(runs))
    ledger=dict(schema_version=1,review_run_id='wrong-run',run_status='complete',
        invocations=[dict(id='call-a')],totals={key:dict(known_subtotal=0,estimated_subtotal=0,
            unknown_invocations=0,conflicted_invocations=0,complete=True)
            for key in ('input_uncached','cache_read','cache_write','input_total','output')})
    (tmp_path/'usage.json').write_text(json.dumps(ledger))
    report,code=evaluate(tmp_path)
    assert code==0 and not report['runs'][0]['cost']['available']
    assert report['runs'][0]['cost']['reason']=='review_run_mismatch'
    ledger['review_run_id']='run-0'; (tmp_path/'usage.json').write_text(json.dumps(ledger))
    report,code=evaluate(tmp_path)
    assert report['runs'][0]['cost']['available'] and report['runs'][0]['cost']['coverage_complete']
    ledger['invocations'].append(dict(id='unattributed')); (tmp_path/'usage.json').write_text(json.dumps(ledger))
    report,code=evaluate(tmp_path)
    assert not report['runs'][0]['cost']['available'] and report['runs'][0]['cost']['reason']=='invocation_scope_mismatch'


def test_split_findings_require_external_review_provenance(tmp_path):
    prepare(tmp_path,findings=[dict(id='f',claim='Compound.',location='docs/example.md:2',split_from='original')])
    assert evaluate(tmp_path)[1]==2


def test_runs_output_uses_canonical_id_order(tmp_path):
    prepare(tmp_path,count=3)
    path=tmp_path/'runs.json'; data=json.loads(path.read_text()); data['runs'].reverse()
    path.write_text(json.dumps(data))
    report,code=evaluate(tmp_path)
    assert code==0 and [r['run_id'] for r in report['runs']]==['run-0','run-1','run-2']


def test_rejected_absence_and_compound_competition(tmp_path):
    sections=prepare(tmp_path)
    gold=json.loads((tmp_path/'gold.json').read_text())
    gold['items']=[dict(id=g,claim='Accepted decision',sections=[sections[0]],disposition='accepted',kind='decision') for g in ('d1','d2')]
    gold['items'].append(dict(id='r',claim='Rejected recommendation',sections=[],disposition='rejected',kind=None))
    (tmp_path/'gold.json').write_text(json.dumps(gold))
    candidates,_=evaluate(tmp_path)
    judgments(tmp_path,candidates,[('f','d1','same_issue'),('f','d2','same_issue')],coverage=True)
    report,code=evaluate(tmp_path,'score')
    assert code==0 and report['runs'][0]['metrics']['decision_recall']['value']==.5
    assert report['runs'][0]['unmatched_gold'][0]['status']=='assignment_dependent'
    assert any(g['id']=='r' and g['disposition']=='rejected' for g in report['gold_items'])


def test_missing_ablation_file_is_unavailable(tmp_path):
    prepare(tmp_path)
    path=tmp_path/'runs.json'; data=json.loads(path.read_text())
    data['runs'][0]['ablations']=[dict(id='missing',stage='blind',passes=['blind-a'],findings='absent.jsonl')]
    path.write_text(json.dumps(data))
    report,code=evaluate(tmp_path)
    assert code==0 and not report['runs'][1]['available']


def test_explicit_ledger_mode_and_shared_loader_immutability(tmp_path):
    prepare(tmp_path)
    path=tmp_path/'findings-0.jsonl'; original=json.loads(path.read_text())
    path.write_text(json.dumps(original)+'\n'+json.dumps(dict(original,status='upheld'))+'\n')
    assert evaluate(tmp_path)[1]==2
    manifest_path=tmp_path/'runs.json'; manifest=json.loads(manifest_path.read_text()); manifest['runs'][0]['input_mode']='ledger'
    manifest_path.write_text(json.dumps(manifest))
    report,code=evaluate(tmp_path)
    assert code==0 and len(report['runs'][0]['findings'])==1
    path.write_text(json.dumps(original)+'\n'+json.dumps(dict(original,claim='Changed immutable claim'))+'\n')
    assert evaluate(tmp_path)[1]==2


def test_resolution_cycle_and_scope_changes_are_invalid(tmp_path):
    prepare(tmp_path); candidates,_=evaluate(tmp_path)
    data=judgments(tmp_path,candidates,[('f','g-d','same_issue')],coverage=True)
    one=dict(data['judgments'][0],id='one',supersedes=['two'])
    two=dict(data['judgments'][0],id='two',supersedes=['one'])
    data['resolutions']=[one,two]; (tmp_path/'judgments.json').write_text(json.dumps(data))
    assert evaluate(tmp_path,'score')[1]==2


def test_cli_roundtrip_candidates_and_score(tmp_path):
    prepare(tmp_path)
    command=[sys.executable,str(ROOT/'scripts/score_review_replay.py')]
    args=['--gold',str(tmp_path/'gold.json'),'--runs',str(tmp_path/'runs.json'),'--json']
    proc=subprocess.run(command+['candidates']+args,capture_output=True,text=True)
    assert proc.returncode==0
    candidate=json.loads(proc.stdout)
    judgments(tmp_path,candidate,[('f','g-d','same_issue')],coverage=True)
    proc=subprocess.run(command+['score']+args+['--judgments',str(tmp_path/'judgments.json')],capture_output=True,text=True)
    assert proc.returncode==0 and json.loads(proc.stdout)['runs'][0]['matching']['decision_matches']==1


def test_synthetic_fixture_example_is_runnable(tmp_path):
    script=ROOT/'tests/fixtures/review-evidence/replay/make_example.py'
    proc=subprocess.run([sys.executable,str(script),'--output',str(tmp_path)],capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    report,code=evaluate(tmp_path,'score')
    assert code==0 and report['runs'][0]['metrics']['decision_recall']['value']==1
    assert report['runs'][0]['metrics']['plain_fix_recall']['value']==1
    assert report['runs'][0]['extras'][0]['status']=='valid'


@pytest.mark.parametrize('positive_attestation',[False,True])
@pytest.mark.parametrize('all_pairs_reviewed',[False,True])
def test_bound_negative_coverage_keeps_unmatched_gold_unresolved(tmp_path,positive_attestation,all_pairs_reviewed):
    prepare(tmp_path); candidates,_=evaluate(tmp_path)
    pairs=[('f','g-d','same_issue')]
    if all_pairs_reviewed:
        pairs.append(('f','g-p','different_issue'))
    data=judgments(tmp_path,candidates,pairs,coverage=True)
    negative=dict(data['coverage'][0],id='negative-coverage',complete=False,
        judge=dict(id='other-human',family='human',kind='human'),reason='Review coverage is incomplete.')
    data['coverage']=(data['coverage'] if positive_attestation else [])+[negative]
    (tmp_path/'judgments.json').write_text(json.dumps(data))
    report,code=evaluate(tmp_path,'score'); scope=report['runs'][0]
    assert code==1 and not scope['semantic_coverage_complete']
    assert not scope['metrics']['plain_fix_recall']['complete']
    assert scope['unmatched_gold']==[dict(gold_id='g-p',status='unresolved')]


@pytest.mark.parametrize('complete',[False,True])
def test_coverage_resolution_explicitly_supersedes_dispute_and_preserves_records(tmp_path,complete):
    prepare(tmp_path); candidates,_=evaluate(tmp_path)
    data=judgments(tmp_path,candidates,[('f','g-d','same_issue')],coverage=True)
    data['coverage'].append(dict(data['coverage'][0],id='negative-coverage',complete=False))
    data['resolutions']=[dict(data['coverage'][0],id='coverage-resolution',complete=complete,
        supersedes=['coverage-0','negative-coverage'])]
    (tmp_path/'judgments.json').write_text(json.dumps(data))
    report,code=evaluate(tmp_path,'score')
    assert code==(0 if complete else 1)
    assert report['runs'][0]['semantic_coverage_complete']==complete
    assert {r['id'] for r in report['coverage']}=={'coverage-0','negative-coverage','coverage-resolution'}
    assert report['runs'][0]['unmatched_gold'][0]['status']==('missed' if complete else 'unresolved')


@pytest.mark.parametrize('problem',['dangling','cross_group','cycle','stale'])
def test_coverage_resolution_requires_same_group_acyclic_current_binding(tmp_path,problem):
    prepare(tmp_path); candidates,_=evaluate(tmp_path)
    data=judgments(tmp_path,candidates,[('f','g-d','same_issue')],coverage=True)
    row=dict(data['coverage'][0],id='coverage-resolution',supersedes=['coverage-0'])
    if problem=='dangling': row['supersedes']=['missing']
    if problem=='cross_group': row['supersedes']=['j-0']
    if problem=='cycle': row['supersedes']=['coverage-resolution']
    if problem=='stale': row['inputs_sha256']='0'*64
    data['resolutions']=[row]; (tmp_path/'judgments.json').write_text(json.dumps(data))
    assert evaluate(tmp_path,'score')[1]==2


@pytest.mark.parametrize('verdict,diagnostic',[
    ('invalid','matched_finding_invalid'),('uncertain','matched_finding_validity_unresolved'),('valid',None)])
def test_matched_findings_keep_extra_validity_and_explicit_diagnostics(tmp_path,verdict,diagnostic):
    prepare(tmp_path); candidates,_=evaluate(tmp_path)
    data=judgments(tmp_path,candidates,[('f','g-d','same_issue')],[('f',verdict,'human')],True)
    report,code=evaluate(tmp_path,'score'); scope=report['runs'][0]
    assert code==0 and assignment(scope['matching']['assignment'])=={'g-d':'f'} and not scope['extras']
    validity=scope['matched_finding_validity'][0]
    assert validity['finding_id']=='f' and validity['gold_id']=='g-d'
    assert validity['status']==verdict and validity['judgment_ids']==['j-1']
    assert validity['diagnostics']==([diagnostic] if diagnostic else [])
    resolution=dict(data['judgments'][1],id='validity-resolution',verdict='valid',supersedes=['j-1'])
    data['resolutions']=[resolution]; (tmp_path/'judgments.json').write_text(json.dumps(data))
    report,code=evaluate(tmp_path,'score')
    assert code==0 and report['runs'][0]['matched_finding_validity'][0]['diagnostics']==[]
    assert len(report['judgments'])==3


@pytest.mark.parametrize('unavailable_ablation',[False,True])
def test_candidates_top_level_reports_semantic_and_unavailable_scope_limits(tmp_path,unavailable_ablation):
    prepare(tmp_path)
    if unavailable_ablation:
        path=tmp_path/'runs.json'; data=json.loads(path.read_text())
        data['runs'][0]['ablations']=[dict(id='missing',stage='blind',passes=['blind-a'])]
        path.write_text(json.dumps(data))
    report,code=evaluate(tmp_path)
    assert code==0 and 'semantic_review_not_evaluated' in report['limitations']
    assert ('ablation_unavailable' in report['limitations'])==unavailable_ablation


@pytest.mark.parametrize('suffix',['٢','2-٤','２','२-4'])
def test_non_ascii_location_digits_do_not_infer_sections(tmp_path,suffix):
    prepare(tmp_path,findings=[dict(id='f',claim='Issue.',location='docs/example.md:'+suffix)])
    report,code=evaluate(tmp_path); scope=report['runs'][0]
    assert code==0 and not scope['candidates']
    assert scope['findings'][0]['diagnostics']==['location_unparseable']
    judgments(tmp_path,report,[('f','g-d','same_issue')],coverage=True)
    scored,code=evaluate(tmp_path,'score')
    assert code==0 and scored['runs'][0]['matching']['decision_matches']==1


@pytest.mark.parametrize('provenance,valid',[
    ({'pass_id':'blind-a'},True),({'pass_ids':['blind-a']},True),
    ({'pass_id':'blind-a','pass_ids':['blind-a','blind-b']},True),
    ({},False),({'pass_ids':[]},False),({'pass_ids':'blind-a'},False),
    ({'pass_id':None},False),({'pass_id':['blind-a']},False),
    ({'pass_id':'outside','pass_ids':['blind-a']},False),
    ({'pass_id':None,'pass_ids':['blind-a']},False),
    ({'pass_id':'blind-a','pass_ids':['blind-b']},False),
    ({'pass_ids':['blind-a','blind-a']},False),
    ({'pass_id':'blind-a','pass_ids':[]},False),
    ({'pass_id':'blind-a','pass_ids':['outside']},False)])
def test_pass_provenance_is_required_validated_and_consistent(tmp_path,provenance,valid):
    prepare(tmp_path)
    path=tmp_path/'runs.json'; manifest=json.loads(path.read_text()); manifest['runs'][0]['passes']=['blind-a','blind-b']
    path.write_text(json.dumps(manifest))
    row=dict(id='f',claim='Issue.',location='docs/example.md:2',**provenance)
    (tmp_path/'findings-0.jsonl').write_text(json.dumps(row)+'\n')
    report,code=evaluate(tmp_path)
    assert code==(0 if valid else 2)


@pytest.mark.parametrize('provenance',[{}, {'pass_id':'blind-b','pass_ids':['blind-a']}])
def test_ablation_cannot_hide_missing_or_out_of_scope_primary_pass(tmp_path,provenance):
    prepare(tmp_path)
    path=tmp_path/'runs.json'; manifest=json.loads(path.read_text()); manifest['runs'][0]['passes']=['blind-a','blind-b']
    manifest['runs'][0]['ablations']=[dict(id='only-a',stage='blind',passes=['blind-a'],findings='pre.jsonl')]
    path.write_text(json.dumps(manifest))
    (tmp_path/'pre.jsonl').write_text(json.dumps(dict(id='f',claim='Issue.',location='docs/example.md:2',**provenance))+'\n')
    assert evaluate(tmp_path)[1]==2


@pytest.mark.parametrize('manifest_change',['run','ablation','token_ledger'])
def test_whole_manifest_edits_invalidate_all_existing_scope_judgments(tmp_path,manifest_change):
    prepare(tmp_path,count=2); candidates,_=evaluate(tmp_path)
    judgments(tmp_path,candidates,[('f','g-d','same_issue')],coverage=True)
    path=tmp_path/'runs.json'; manifest=json.loads(path.read_text())
    if manifest_change=='run':
        manifest['runs'].append(dict(manifest['runs'][0],id='new-run'))
    elif manifest_change=='ablation':
        manifest['runs'][0]['ablations']=[dict(id='missing',stage='blind',passes=['blind-a'])]
    else:
        manifest['runs'][0]['token_ledger']='usage.json'
    path.write_text(json.dumps(manifest))
    newer,code=evaluate(tmp_path)
    assert code==0
    for old in candidates['runs']:
        current=next(r for r in newer['runs'] if r['run_id']==old['run_id'] and r['ablation_id'] is None)
        assert current['inputs_sha256']!=old['inputs_sha256']
    report,code=evaluate(tmp_path,'score')
    assert code==2 and report['reasons']==['stale_judgment_binding']
