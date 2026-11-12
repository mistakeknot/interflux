#!/usr/bin/env python3
"""Offline accepted-gold replay scorer. No model calls or automatic semantic matching.

Gold JSON: {schema_version:1, snapshot:{...}, index:path, items:[...]}
Runs JSON: {schema_version:1, runs:[{id,snapshot,findings,input_mode,stage,passes,
  invocation_ids?,token_ledger?,ablations?:[{id,stage,passes,findings?,...}]}]}
Judgments JSON: {schema_version:1, judgments:[], resolutions:[], coverage:[]}.
See synthetic replay fixture documentation for the external judgment contract.
"""
from __future__ import annotations

import argparse
from collections import defaultdict,deque
from pathlib import Path
import re
import math

from _review_evidence import (PARSER_VERSION,canonical_json,digest,document_id,load_findings,
    parser_hash,read_json,seal_index,source_lines)
from _review_replay import PriorityMatcher
from _review_usage import FIELDS as USAGE_FIELDS,REQUIRED as REQUIRED_USAGE

SNAPSHOT_KEYS=('document_id','document_sha256','parser_version','parser_sha256','syntax_profile','index_sha256')


class ReplayError(ValueError):
    pass


def require(ok,code='invalid_structure'):
    if not ok:
        raise ReplayError(code)


def identifier(value):
    return isinstance(value,str) and 0<len(value)<=128 and value.isprintable() and not any(c in value for c in '/\\')


def alias(value):
    return isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}',value) is not None


def hash_value(value):
    return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None


def load(path):
    data=Path(path).read_bytes()
    return read_json(data.decode('utf-8')),digest(data)


def relative(base,value):
    require(isinstance(value,str),'invalid_relative_path')
    return base/document_id(value)


def string_set(value,predicate=identifier,nonempty=False):
    require(isinstance(value,list) and (not nonempty or value) and all(predicate(v) for v in value))
    require(len(value)==len(set(value)),'duplicate_set_member')
    return sorted(value)


def version(value):
    require(isinstance(value,dict) and type(value.get('schema_version')) is int and value['schema_version']==1,'schema_unsupported')


def snapshot(value):
    require(isinstance(value,dict) and set(value)==set(SNAPSHOT_KEYS),'invalid_snapshot')
    require(value['document_id']==document_id(value['document_id']),'invalid_snapshot')
    require(all(hash_value(value[key]) for key in ('document_sha256','parser_sha256','index_sha256')),'invalid_snapshot')
    require(value['parser_version']==PARSER_VERSION and value['parser_sha256']==parser_hash(),'parser_contract_mismatch')
    profile=value['syntax_profile']
    if profile is not None:
        require(isinstance(profile,dict) and set(profile)=={'id','version','sha256'} and alias(profile['id'])
            and type(profile['version']) is int and profile['version']>0 and hash_value(profile['sha256']),'invalid_profile_identity')
    return value


def load_gold(path):
    gold,gold_hash=load(path); version(gold)
    require(set(gold)=={'schema_version','snapshot','index','items'})
    snap=snapshot(gold['snapshot'])
    index,index_hash=load(relative(Path(path).parent,gold['index'])); version(index)
    require({key:index.get(key) for key in SNAPSHOT_KEYS}==snap,'index_snapshot_mismatch')
    require(seal_index(index)['index_sha256']==index['index_sha256'],'index_hash_mismatch')
    require(isinstance(index.get('sections'),list) and index['sections'],'invalid_index_sections')
    ids=set(); expected=1
    for section in index['sections']:
        require(isinstance(section,dict) and identifier(section.get('section_id')),'invalid_index_section')
        require(section['section_id'] not in ids,'duplicate_section_id'); ids.add(section['section_id'])
        interval=section.get('line_range',{})
        require(type(interval.get('start')) is int and type(interval.get('end')) is int,'invalid_index_range')
        require(interval['start']==expected and interval['end']>=expected-1,'index_ownership_gap_or_overlap')
        expected=interval['end']+1
    require(isinstance(gold['items'],list))
    items=[]; seen=set(); labels=True
    for row in gold['items']:
        require(isinstance(row,dict) and identifier(row.get('id')) and isinstance(row.get('claim'),str) and row['claim'])
        require(row['id'] not in seen,'duplicate_gold_id'); seen.add(row['id'])
        disposition,kind=row.get('disposition'),row.get('kind')
        require(disposition in ('accepted','rejected',None) and kind in ('decision','plain_fix',None),'invalid_gold_label')
        sections=string_set(row.get('sections'))
        require(set(sections)<=ids,'unknown_gold_section')
        if disposition is None or disposition=='accepted' and kind is None:
            labels=False
        items.append(dict(row,disposition=disposition,kind=kind,sections=sections))
    return dict(snapshot=snap,index=index,items=sorted(items,key=lambda r:r['id']),labels_complete=labels,
        gold_sha256=gold_hash,index_file_sha256=index_hash,line_count=expected-1)


def resolve_sections(row,gold):
    declared=string_set(row['sections']) if 'sections' in row else None
    ids={s['section_id'] for s in gold['index']['sections']}
    require(declared is None or set(declared)<=ids,'unknown_finding_section')
    derived=[]; diagnostics=[]
    match=re.fullmatch(r'(.+):(\d+)(?:-(\d+))?',row['location'])
    if not match:
        diagnostics.append('location_unparseable')
    else:
        try:
            path=document_id(match[1])
        except ValueError:
            path=None
        start,end=int(match[2]),int(match[3] or match[2])
        if path is None:
            diagnostics.append('location_unparseable')
        elif path!=gold['snapshot']['document_id']:
            diagnostics.append('location_other_document')
        elif not (1<=start<=end<=gold['line_count']):
            diagnostics.append('location_out_of_bounds')
        else:
            derived=sorted(s['section_id'] for s in gold['index']['sections']
                if s['line_range']['start']<=end and s['line_range']['end']>=start)
    if declared is not None and declared!=derived:
        diagnostics.append('section_disagreement')
    return dict(id=row['id'],declared_sections=declared,derived_sections=derived,
        effective_sections=derived,diagnostics=diagnostics)


def load_findings_file(path,mode,gold,passes):
    data=path.read_bytes(); text=data.decode('utf-8')
    if not text.strip():
        rows=[]
    else:
        try:
            value=read_json(text)
            rows=value['findings'] if isinstance(value,dict) and 'findings' in value else value if isinstance(value,list) else [value]
        except ValueError:
            rows=[read_json(line) for line in source_lines(text) if line.strip()]
    effective,loader=load_findings(rows,mode)
    result=[]
    for row in effective:
        require(identifier(row['id']),'invalid_finding_id')
        row_passes=string_set(row['pass_ids'],alias) if 'pass_ids' in row else [row['pass_id']] if 'pass_id' in row else []
        require(set(row_passes)<=set(passes),'finding_pass_outside_scope')
        if 'split_from' in row:
            provenance=row.get('split_provenance')
            require(identifier(row['split_from']) and isinstance(provenance,dict)
                and set(provenance)=={'judgment_id','judge','reason','source_findings_sha256'}
                and identifier(provenance['judgment_id']) and judge_valid(provenance['judge'])
                and isinstance(provenance['reason'],str) and provenance['reason']
                and hash_value(provenance['source_findings_sha256']),'unreviewed_split')
        result.append(dict(original=row,resolved=resolve_sections(row,gold)))
    return sorted(result,key=lambda r:r['original']['id']),digest(data),loader


def load_scopes(path,gold):
    manifest,manifest_hash=load(path); version(manifest)
    require(set(manifest)=={'schema_version','runs'} and isinstance(manifest['runs'],list) and manifest['runs'],'invalid_runs')
    scopes=[]; ids=set()
    for run in manifest['runs']:
        require(isinstance(run,dict) and alias(run.get('id')) and run['id'] not in ids,'invalid_run_id'); ids.add(run['id'])
        require(snapshot(run.get('snapshot'))==gold['snapshot'],'run_snapshot_mismatch')
        require(set(run)<= {'id','snapshot','findings','input_mode','stage','passes','invocation_ids','token_ledger','ablations'})
        base_passes=string_set(run.get('passes'),alias,True)
        entries=[(None,run)]; ablations=run.get('ablations',[])
        require(isinstance(ablations,list)); ablation_ids=set()
        for ablation in ablations:
            require(isinstance(ablation,dict) and alias(ablation.get('id')) and ablation['id'] not in ablation_ids,'invalid_ablation_id')
            require(set(ablation)<={'id','findings','input_mode','stage','passes','invocation_ids','token_ledger'})
            ablation_ids.add(ablation['id']); entries.append((ablation['id'],ablation))
        for ablation_id,entry in entries:
            passes=string_set(entry.get('passes'),alias,True)
            require(set(passes)<=set(base_passes),'invalid_ablation_passes')
            require(alias(entry.get('stage')),'invalid_stage')
            mode=entry.get('input_mode',run.get('input_mode'))
            require(mode in ('snapshot','ledger'),'invalid_input_mode')
            invocations=string_set(entry.get('invocation_ids',[]),alias)
            scope=dict(run_id=run['id'],ablation_id=ablation_id,stage=entry['stage'],passes=passes,invocation_ids=invocations)
            if not entry.get('findings'):
                require(ablation_id is not None,'missing_run_findings')
                scopes.append(dict(scope,available=False,reasons=['ablation_data_missing'])); continue
            artifact=relative(Path(path).parent,entry['findings'])
            if ablation_id is not None and artifact==relative(Path(path).parent,run['findings']):
                scopes.append(dict(scope,available=False,reasons=['ablation_artifact_not_separate'])); continue
            try:
                findings,file_hash,loader=load_findings_file(artifact,mode,gold,passes)
            except FileNotFoundError:
                if ablation_id is None:
                    raise
                scopes.append(dict(scope,available=False,reasons=['ablation_data_missing'])); continue
            envelope=dict(schema_version=1,scope=scope,snapshot=gold['snapshot'],
                input_sha256=dict(gold=gold['gold_sha256'],index=gold['index_file_sha256'],runs_manifest=manifest_hash,findings=file_hash),
                gold=gold['items'],findings=findings,input_mode=mode,loader_version='review-findings-v1',section_derivation_version='direct-line-ranges-v1')
            scopes.append(dict(scope,available=True,inputs_sha256=digest(canonical_json(envelope)),
                _findings=findings,_token_ledger=entry.get('token_ledger'),_directory=Path(path).parent,
                findings=[f['resolved'] for f in findings],row_diagnostics=loader,
                candidates=[dict(finding_id=f['original']['id'],gold_id=g['id'],basis='section_overlap')
                    for f in findings for g in gold['items'] if set(f['resolved']['effective_sections'])&set(g['sections'])],
                candidate_generation_complete=True,semantic_coverage_complete=False))
    return sorted(scopes,key=lambda s:(s['run_id'],s['ablation_id'] is not None,s['ablation_id'] or ''))


def judge_valid(judge):
    return isinstance(judge,dict) and {'id','kind','family'}<=set(judge) and set(judge)<={'id','kind','family','model','receipt_id'} and identifier(judge['id']) and alias(judge['family']) and judge['kind'] in ('human','model') and all(identifier(judge[k]) for k in ('model','receipt_id') if k in judge)


def group_key(row):
    return row['run_id'],row.get('ablation_id'),row['type'],row.get('finding_id'),row.get('gold_id')


def load_judgments(path,scopes,gold):
    data=dict(schema_version=1,judgments=[],resolutions=[],coverage=[]) if path is None else load(path)[0]
    version(data); require(set(data)<={'schema_version','judgments','resolutions','coverage'})
    by_scope={(s['run_id'],s['ablation_id']):s for s in scopes if s['available']}
    gold_ids={g['id'] for g in gold['items']}; all_ids=set(); records=[]; coverage=[]
    for category in ('judgments','resolutions','coverage'):
        require(isinstance(data.get(category,[]),list))
        for raw in data.get(category,[]):
            require(isinstance(raw,dict) and identifier(raw.get('id')) and raw['id'] not in all_ids,'duplicate_judgment_id')
            all_ids.add(raw['id']); row=dict(raw,ablation_id=raw.get('ablation_id'))
            allowed={'id','run_id','ablation_id','type','inputs_sha256','judge','reason'}
            is_coverage=category=='coverage' or category=='resolutions' and row.get('type')=='semantic'
            allowed|={'complete'} if is_coverage else {'finding_id','gold_id','verdict'}
            if category=='resolutions':
                allowed.add('supersedes')
            require(set(row)<=allowed and judge_valid(row.get('judge')) and isinstance(row.get('reason'),str) and row['reason'],'invalid_judgment')
            row['reason'].encode('utf-8')
            scope=by_scope.get((row.get('run_id'),row['ablation_id']))
            require(scope is not None,'dangling_scope')
            require(row.get('inputs_sha256')==scope['inputs_sha256'],'stale_judgment_binding')
            if category=='resolutions':
                row['supersedes']=string_set(row.get('supersedes'),identifier,True)
            if is_coverage:
                require(row.get('type')=='semantic' and type(row.get('complete')) is bool,'invalid_coverage')
                coverage.append(row); continue
            require(row.get('finding_id') in {f['original']['id'] for f in scope['_findings']},'dangling_finding')
            kind=row.get('type')
            require(kind in ('match','extra'),'invalid_judgment_type')
            if kind=='match':
                require(row.get('gold_id') in gold_ids,'dangling_gold')
                require(row.get('verdict') in ('same_issue','different_issue','uncertain'),'invalid_match_verdict')
            else:
                require('gold_id' not in row and row.get('verdict') in ('valid','invalid','uncertain'),'invalid_extra_verdict')
            records.append(row)
    all_records=records+coverage
    by_id={r['id']:r for r in all_records}; removed=set(); adjacency={r['id']:[] for r in all_records}; degrees=dict.fromkeys(by_id,0)
    for row in all_records:
        for target in row.get('supersedes',[]):
            require(target in by_id and group_key(by_id[target])==group_key(row),'invalid_superseded_reference')
            adjacency[row['id']].append(target); degrees[target]+=1; removed.add(target)
    queue=deque(sorted(k for k,v in degrees.items() if v==0)); visited=0
    while queue:
        node=queue.popleft(); visited+=1
        for target in adjacency[node]:
            degrees[target]-=1
            if degrees[target]==0:
                queue.append(target)
    require(visited==len(all_records),'resolution_cycle')
    groups=defaultdict(list)
    for row in all_records:
        if row['id'] not in removed:
            groups[group_key(row)].append(row)
    return sorted(records,key=lambda r:r['id']),sorted(coverage,key=lambda r:r['id']),groups


def resolved(rows):
    values={row['verdict'] for row in rows}
    return next(iter(values)) if len(values)==1 else 'uncertain'


def score_scope(scope,gold,groups):
    eligible={g['id']:g['kind'] for g in gold['items'] if g['disposition']=='accepted' and g['kind'] in ('decision','plain_fix')}
    fids=[f['original']['id'] for f in scope['_findings']]
    run,ablation=scope['run_id'],scope['ablation_id']
    matches={(f,g):rows for (r,a,kind,f,g),rows in groups.items() if (r,a,kind)==(run,ablation,'match')}
    edges={(f,g) for (f,g),rows in matches.items() if g in eligible and resolved(rows)=='same_issue'}
    result=PriorityMatcher(eligible,fids,edges).analyze()
    chosen={r['gold_id']:r['finding_id'] for r in result['matching']['assignment']}
    active_coverage=groups.get((run,ablation,'semantic',None,None),[])
    coverage_blocked=any(not c['complete'] for c in active_coverage)
    attested=bool(active_coverage) and not coverage_blocked
    all_pairs={(f,g) for f in fids for g in eligible}
    complete_pairs={pair for pair,rows in matches.items() if pair in all_pairs and resolved(rows)!='uncertain'}
    unresolved_pairs=any(pair in all_pairs and resolved(rows)=='uncertain' for pair,rows in matches.items())
    semantic=(attested or complete_pairs==all_pairs) and not unresolved_pairs and not coverage_blocked
    metrics={}
    for kind,key in (('decision','decision_recall'),('plain_fix','plain_fix_recall')):
        denominator=sum(value==kind for value in eligible.values()); matched=sum(eligible[g]==kind for g in chosen)
        metrics[key]=dict(denominator=denominator,denominator_complete=gold['labels_complete'],confirmed_matches=matched,
            value=matched/denominator if denominator and gold['labels_complete'] else None,complete=semantic and gold['labels_complete'])
    rejected={g['id'] for g in gold['items'] if g['disposition']=='rejected'}
    rejected_relations=[dict(finding_id=f,gold_id=g,judgment_ids=sorted(r['id'] for r in rows))
        for (f,g),rows in sorted(matches.items()) if g in rejected and resolved(rows)=='same_issue']
    extras=[]; matched_validity=[]; by_f={r['finding_id']:r for r in result['ambiguity']['per_finding']}
    matched_gold={f:g for g,f in chosen.items()}
    for f in sorted(fids):
        rows=groups.get((run,ablation,'extra',f,None),[])
        if f in matched_gold and not rows:
            continue
        verdict=resolved(rows) if rows else 'unverified'
        families=sorted({r['judge']['family'] for r in rows if r['judge']['kind']=='model'})
        human=any(r['judge']['kind']=='human' for r in rows)
        validity=dict(finding_id=f,status=verdict,judgment_ids=sorted(r['id'] for r in rows),
            model_families=families,three_family_coverage=len(families)>=3,
            family_coverage_basis='declared_judge_provenance',
            complete=verdict in ('valid','invalid') and (human or len(families)>=3),
            occurrence_ambiguous=by_f[f]['occurrence_ambiguous'])
        if f in matched_gold:
            diagnostics=['matched_finding_invalid'] if verdict=='invalid' else ['matched_finding_validity_unresolved'] if verdict=='uncertain' else []
            matched_validity.append(dict(validity,gold_id=matched_gold[f],diagnostics=diagnostics))
        else:
            extras.append(validity)
    by_g={r['gold_id']:r for r in result['ambiguity']['per_gold']}
    unmatched=[dict(gold_id=g,status='unresolved' if not semantic or not gold['labels_complete'] else
        'assignment_dependent' if by_g[g]['occurrence_ambiguous'] else 'missed') for g in sorted(eligible) if g not in chosen]
    return dict(result,labels_complete=gold['labels_complete'],semantic_coverage_complete=semantic,metrics=metrics,
        recall_status='incomplete_labels' if not gold['labels_complete'] else 'complete' if semantic else 'confirmed_recall_lower_bound',
        unmatched_gold=unmatched,rejected_relations=rejected_relations,extras=extras,matched_finding_validity=matched_validity,
        complete=gold['labels_complete'] and semantic and all(e['complete'] for e in extras))


def cost_summary(scope):
    if scope['_token_ledger'] is None:
        return dict(available=False,reason='not_requested')
    try:
        ledger,sha=load(relative(scope['_directory'],scope['_token_ledger'])); version(ledger)
        if ledger.get('review_run_id')!=scope['run_id']:
            return dict(available=False,reason='review_run_mismatch')
        rows=ledger.get('invocations')
        require(isinstance(rows,list) and all(isinstance(r,dict) and alias(r.get('id')) for r in rows))
        ids=[r['id'] for r in rows]
        if not scope['invocation_ids'] or len(ids)!=len(set(ids)) or set(ids)!=set(scope['invocation_ids']):
            return dict(available=False,reason='invocation_scope_mismatch')
        totals=ledger.get('totals'); require(isinstance(totals,dict))
        projected={}
        for key in USAGE_FIELDS:
            if key not in totals:
                continue
            value=totals[key]
            require(isinstance(value,dict) and type(value.get('complete')) is bool)
            fields=('known_subtotal','estimated_subtotal','unknown_invocations','conflicted_invocations')
            require(all(type(value.get(f)) is int and value[f]>=0 for f in fields))
            projected[key]={f:value[f] for f in (*fields,'complete')}
        complete=ledger.get('run_status')=='complete' and all(projected.get(k,{}).get('complete') is True for k in REQUIRED_USAGE)
        result=dict(available=True,ledger_sha256=sha,coverage_complete=complete,totals=projected)
        estimate=ledger.get('estimated_list_cost')
        if estimate is not None:
            require(isinstance(estimate,dict) and type(estimate.get('complete')) is bool and
                isinstance(estimate.get('currency'),str) and re.fullmatch('[A-Z]{3}',estimate['currency']) and
                isinstance(estimate.get('effective_date'),str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',estimate['effective_date']) and
                estimate.get('basis')=='estimated_list_prices')
            for field in ('value','known_subtotal'):
                v=estimate.get(field)
                require(v is None or type(v) in (int,float) and math.isfinite(v) and v>=0)
            result['estimated_list_cost']={k:estimate.get(k) for k in ('value','known_subtotal','currency','effective_date','complete','basis')}
        return result
    except (ValueError,TypeError,KeyError,OSError,RecursionError):
        return dict(available=False,reason='invalid_cost_evidence')


def evaluate_files(gold_path,runs_path,judgments_path=None,mode='candidates'):
    try:
        require(mode in ('candidates','score'),'invalid_mode')
        gold=load_gold(gold_path); scopes=load_scopes(runs_path,gold)
        records,coverage,groups=load_judgments(judgments_path,scopes,gold) if mode=='score' else ([],[],{})
        results=[]
        for scope in scopes:
            public={k:v for k,v in scope.items() if not k.startswith('_')}
            if scope['available']:
                public['cost']=cost_summary(scope)
            if scope['available'] and mode=='score':
                public.update(score_scope(scope,gold,groups))
                if scope['_token_ledger'] is not None and not public['cost'].get('coverage_complete',False):
                    public['complete']=False
            results.append(public)
        complete=all(r['available'] and r.get('complete',False) for r in results)
        limitations=['semantic_review_not_evaluated'] if mode=='candidates' else []
        if any(not r['available'] for r in results):
            limitations.append('ablation_unavailable')
        report=dict(schema_version=1,mode=mode,run_status='complete' if complete or mode=='candidates' else 'incomplete',
            snapshot=gold['snapshot'],labels_complete=gold['labels_complete'],limitations=limitations,runs=results,
            gold_items=[dict(id=g['id'],disposition=g['disposition'],kind=g['kind'],
                eligible=g['disposition']=='accepted' and g['kind'] in ('decision','plain_fix')) for g in gold['items']],
            judgments=records,coverage=coverage)
        return report,0 if mode=='candidates' or complete else 1
    except ReplayError as exc:
        return dict(schema_version=1,run_status='invalid_input',reasons=[str(exc)]),2
    except (ValueError,TypeError,KeyError,OSError,AttributeError,RecursionError):
        return dict(schema_version=1,run_status='invalid_input',reasons=['invalid_input']),2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('candidates','score'))
    parser.add_argument('--gold',required=True); parser.add_argument('--runs',required=True)
    parser.add_argument('--judgments'); parser.add_argument('--json',action='store_true')
    args=parser.parse_args()
    report,code=evaluate_files(args.gold,args.runs,args.judgments,args.mode)
    print(canonical_json(report).decode(),end='')
    return code


if __name__=='__main__':
    raise SystemExit(main())
