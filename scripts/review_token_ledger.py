#!/usr/bin/env python3
"""Build an offline, manifest-relative token ledger, without transcript contents.

Sources: clavain-receipt-v1 (dispatch/optional attempt selector),
claude-assistant-v1 (session_id + message_ids), codex-events-v1 (session_id +
zero-based physical record_indices), claude-cumulative-v1 (dispatch_id +
invocation_id), claude-result-v1 (session_id + exactly one record index).

Each invocation represents one explicitly declared attempt. Sources are alternate
views, not additional charges. Estimates require category/value/scope/method.
Optional price JSON: schema_version 1, currency, effective_date, models mapping
observed model to per-million category rates (or TTL-specific cache-write rates).
Exit 0: complete relative to manifest; 1: incomplete/conflicted; 2: invalid input.
"""
from __future__ import annotations

import argparse
import datetime
import math
import re
from pathlib import Path

from _review_evidence import canonical_json,read_json
from _review_usage import FIELDS,REQUIRED,adapt,empty_fields,number,model,effort


def alias(value):
    return isinstance(value,str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}',value))


def validate(manifest,prices):
    if not isinstance(manifest,dict) or set(manifest)!={'schema_version','review_run_id','invocations'} or manifest['schema_version']!=1 or not alias(manifest['review_run_id']) or not isinstance(manifest['invocations'],list) or not manifest['invocations']:
        raise ValueError()
    ids=set()
    for inv in manifest['invocations']:
        if not isinstance(inv,dict) or set(inv)-{'id','pass_id','role','sources','estimates'} or not {'id','pass_id','role','sources'}<=set(inv):
            raise ValueError()
        if not all(alias(inv.get(k)) for k in ('id','pass_id','role')) or inv['id'] in ids or not isinstance(inv['sources'],list):
            raise ValueError()
        ids.add(inv['id']); aliases=set()
        for s in inv['sources']:
            if not isinstance(s,dict) or set(s)-{'source_id','format','path','selector','related_selector'} or not all(k in s for k in ('source_id','format','path')) or not alias(s['source_id']) or not alias(s['format']) or not isinstance(s['path'],str) or not s['path'] or '\0' in s['path'] or s['source_id'] in aliases:
                raise ValueError()
            aliases.add(s['source_id'])
            if not isinstance(s.get('selector',{}),dict):
                raise ValueError()
            related=s.get('related_selector')
            if related is not None and (not isinstance(related,dict) or not related or set(related)-{'thread_id','bead_id','session_id'} or not all(isinstance(v,str) and v for v in related.values())):
                raise ValueError()
        estimates=inv.get('estimates',[])
        if not isinstance(estimates,list):
            raise ValueError()
        cats=set()
        for est in estimates:
            if not isinstance(est,dict) or set(est)!={'category','value','scope','method'} or est['category'] not in FIELDS or number(est['value']) is None or est['scope']!=inv['id'] or not alias(est['method']) or est['category'] in cats:
                raise ValueError()
            cats.add(est['category'])
    if prices is not None:
        if not isinstance(prices,dict) or set(prices)!={'schema_version','currency','effective_date','models'} or prices['schema_version']!=1 or not isinstance(prices['currency'],str) or not re.fullmatch('[A-Z]{3}',prices['currency']) or not isinstance(prices['models'],dict):
            raise ValueError()
        datetime.date.fromisoformat(prices['effective_date'])
        for name,rates in prices['models'].items():
            if model(name) is None or not isinstance(rates,dict) or set(rates)-set(FIELDS) or any(type(n) not in (int,float) or not math.isfinite(n) or n<0 for n in rates.values()):
                raise ValueError()


def reconcile(inv,sources):
    usage=empty_fields(); conflicts=[]
    preferred=sorted(enumerate(sources),key=lambda pair:(not pair[1]['complete'],pair[1]['format']=='clavain-receipt-v1',pair[0]))
    for key in FIELDS:
        candidates=[s['usage'][key] for _,s in preferred if s['usage'][key]['value'] is not None]
        values={f['value'] for f in candidates}
        if len(values)>1:
            conflicts.append(key)
        elif candidates:
            usage[key]=candidates[0].copy()
    for est in inv.get('estimates',[]):
        key=est['category']
        if usage[key]['value'] is None and key not in conflicts:
            usage[key]=dict(value=est['value'],quality='estimated',complete=False)
    actual={s['actual_model'] for s in sources if s['actual_model'] is not None}
    row=dict(id=inv['id'],pass_id=inv['pass_id'],role=inv['role'],usage=usage,conflicts=conflicts,
        actual_model=next(iter(actual)) if len(actual)==1 else None,
        requested_model=next((s['requested_model'] for _,s in preferred if s['requested_model']),None),
        actual_effort=next((s['actual_effort'] for _,s in preferred if s['actual_effort']),None),
        requested_effort=next((s['requested_effort'] for _,s in preferred if s['requested_effort']),None),
        lifecycle=next((s['lifecycle'] for _,s in preferred if s['lifecycle']!='unknown'),'unknown'),
        estimates=inv.get('estimates',[]),sources=[{k:v for k,v in s.items() if not k.startswith('_') and k!='usage'} for s in sources],
        reasons=sorted({r for s in sources for r in s['reasons']}),complete=all(usage[k]['complete'] for k in REQUIRED))
    if conflicts:
        row['reasons'].append('usage_conflict'); row['complete']=False
    if len(actual)>1:
        row['reasons'].append('model_conflict'); row['complete']=False
    fatal={'duplicate_receipt_conflict','message_identity_conflict','session_identity_conflict',
        'cumulative_sequence_conflict','cumulative_counter_regression','malformed_usage_record',
        'ambiguous_attempt_selection','parent_scope_unknown','model_conflict','model_identity_conflict'}
    if fatal & set(row['reasons']):
        row['complete']=False
        for field in row['usage'].values():
            field['complete']=False
    return row


def estimate_cost(rows,prices):
    subtotal=0; missing=0
    for row in rows:
        rates=prices['models'].get(row['actual_model'],{})
        usage=row['usage']; complete=True; value=0
        for key in ('input_uncached','cache_read','output'):
            field=usage[key]
            if field['value'] is None or key not in rates or not field['complete']:
                complete=False
            else:
                value+=field['value']*rates[key]/1_000_000
        write=usage['cache_write']
        if write['value']==0 and write['complete']:
            pass
        elif 'cache_write' in rates and write['value'] is not None and write['complete']:
            value+=write['value']*rates['cache_write']/1_000_000
        elif all(usage[k]['value'] is not None and usage[k]['complete'] and k in rates for k in ('cache_write_5m','cache_write_1h')) and write['value']==usage['cache_write_5m']['value']+usage['cache_write_1h']['value']:
            value+=sum(usage[k]['value']*rates[k]/1_000_000 for k in ('cache_write_5m','cache_write_1h'))
        else:
            complete=False
        subtotal+=value
        if not complete:
            missing+=1
    return dict(value=subtotal if not missing else None,known_subtotal=subtotal,currency=prices['currency'],
        effective_date=prices['effective_date'],complete=not missing,unknown_invocations=missing,basis='estimated_list_prices')


def build_ledger(manifest,directory,prices=None):
    try:
        validate(manifest,prices)
    except (ValueError,TypeError,KeyError,AttributeError):
        return dict(schema_version=1,run_status='invalid_input',reasons=['invalid_manifest_or_prices']),2
    directory=Path(directory); all_sources=[]; rows=[]; listed=set(); related=set(); related_enabled=False; related_unknown=False
    for inv in manifest['invocations']:
        sources=[adapt(s,directory) for s in inv['sources']]
        all_sources.append(sources); rows.append(reconcile(inv,sources))
        for definition,s in zip(inv['sources'],sources):
            listed.update(s['_listed']); related.update(s['_related'])
            related_enabled=related_enabled or 'related_selector' in definition
            related_unknown=related_unknown or s['_related_unknown']
    # Physical identities may not be charged to two manifest invocation aliases.
    for i in range(len(rows)):
        for j in range(i):
            first,second=all_sources[i],all_sources[j]
            overlap=any(a['_coverage']&b['_coverage'] or a['_whole_sessions']&b['_sessions'] or b['_whole_sessions']&a['_sessions'] for a in first for b in second)
            if overlap:
                for n in (i,j):
                    rows[n]['usage']=empty_fields(); rows[n]['complete']=False
                    rows[n]['reasons']=sorted(set(rows[n]['reasons']+['overlapping_invocations']))
    totals={}
    for key in FIELDS:
        fields=[r['usage'][key] for r in rows]
        totals[key]=dict(known_subtotal=sum(f['value'] for f in fields if f['value'] is not None and f['quality']!='estimated'),
            estimated_subtotal=sum(f['value'] for f in fields if f['value'] is not None and f['quality']=='estimated'),
            unknown_invocations=sum(not f['complete'] for r,f in zip(rows,fields) if key not in r['conflicts']),
            conflicted_invocations=sum(key in r['conflicts'] for r in rows),complete=all(f['complete'] for f in fields))
    report=dict(schema_version=1,run_status='complete' if all(r['complete'] for r in rows) else 'incomplete',
        review_run_id=manifest['review_run_id'],coverage_basis='manifest_declared',declared_invocations=len(rows),
        unlisted_related_receipts=len(related-listed) if related_enabled and not related_unknown else None,invocations=rows,totals=totals)
    if prices is not None:
        report['estimated_list_cost']=estimate_cost(rows,prices)
    complete=all(r['complete'] for r in rows) and (prices is None or report['estimated_list_cost']['complete'])
    report['run_status']='complete' if complete else 'incomplete'
    return report,0 if complete else 1


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',required=True); p.add_argument('--prices'); p.add_argument('--json',action='store_true')
    args=p.parse_args()
    try:
        path=Path(args.manifest)
        manifest=read_json(path.read_text(encoding='utf-8'))
        prices=read_json(Path(args.prices).read_text(encoding='utf-8')) if args.prices else None
        report,code=build_ledger(manifest,path.parent,prices)
    except (OSError,ValueError,TypeError):
        report,code=dict(schema_version=1,run_status='invalid_input',reasons=['invalid_input']),2
    print(canonical_json(report).decode(),end='')
    return code


if __name__=='__main__':
    raise SystemExit(main())
