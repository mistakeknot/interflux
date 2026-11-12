"""Versioned, offline usage adapters; see the synthetic usage fixture contract.

Clavain 0.6.332 receipts and Claude cumulative schema 1 are supported. Codex
multi-turn scope is deliberately unsupported: a receipt's sum is not independent
proof that provider counters are additive. Select explicit records/messages; no
timestamp attribution or transcript discovery. Only numeric observations and
allowlisted metadata leave this module. Source identities stay internal.
"""
from __future__ import annotations

import re
from pathlib import Path

from _review_evidence import canonical_json, read_json, source_lines

FIELDS=('input_uncached','cache_read','cache_write','input_total','output',
        'reasoning_output','cache_write_5m','cache_write_1h')
REQUIRED=FIELDS[:5]
CLAUDE_KEYS={'input_uncached':'input_tokens','cache_read':'cache_read_input_tokens',
    'cache_write':'cache_creation_input_tokens','output':'output_tokens'}
RECEIPT_KEYS={'input_uncached':'tokens_in','cache_read':'tokens_cached_in',
    'cache_write':'tokens_cache_write_in','output':'tokens_out','reasoning_output':'tokens_reasoning_out'}


def number(value):
    return value if type(value) is int and 0 <= value <= 2**53 else None


def model(value):
    return value if isinstance(value,str) and re.fullmatch(r'(?:claude-|gpt-|codex-|o[1-9]|model-)[a-zA-Z0-9._-]{0,100}',value) else None


def effort(value):
    return value if value in ('minimal','low','medium','high','xhigh','max','ultra') else None


def state(value):
    return value if value in ('running','completed','failed','discarded','abandoned','cancelled') else 'unknown'


def empty_fields():
    return {k:dict(value=None,quality='unknown',complete=False) for k in FIELDS}


def observation(alias,fmt):
    return dict(source_id=alias,format=fmt,usage_status=None,basis=None,usage=empty_fields(),raw_counts=[],
        requested_model=None,actual_model=None,requested_effort=None,actual_effort=None,lifecycle='unknown',
        reasons=[],complete=False,_coverage=set(),_sessions=set(),_whole_sessions=set(),_related=set(),_listed=set(),_related_unknown=False,
        _provider_binding=None,_binding_validated=False)


def normalize(raw,basis,complete,reasons):
    fields=empty_fields()
    for key in FIELDS:
        n=number(raw.get(key))
        if key in raw and raw[key] is not None and n is None:
            reasons.append('invalid_count')
        if n is not None:
            fields[key]=dict(value=n,quality='measured',complete=complete)
    if basis=='codex-input-includes-cached':
        fields['input_total']=fields['input_uncached'].copy()
        total,cached=fields['input_total']['value'],fields['cache_read']['value']
        fields['input_uncached']=dict(value=None,quality='unknown',complete=False)
        if total is not None and cached is not None:
            if cached>total:
                reasons.append('cached_exceeds_input')
            else:
                fields['input_uncached']=dict(value=total-cached,quality='derived',complete=complete)
    elif basis=='claude-input-excludes-cache':
        needed=[fields[k]['value'] for k in ('input_uncached','cache_read','cache_write')]
        if all(n is not None for n in needed):
            fields['input_total']=dict(value=sum(needed),quality='derived',complete=complete)
    else:
        reasons.append('usage_basis_unknown')
        return empty_fields()
    if (fields['reasoning_output']['value'] is not None and fields['output']['value'] is not None
            and fields['reasoning_output']['value']>fields['output']['value']):
        reasons.append('invalid_reasoning_subset')
    ttl=[fields[k]['value'] for k in ('cache_write_5m','cache_write_1h')]
    if fields['cache_write']['value'] is not None and sum(n for n in ttl if n is not None)>fields['cache_write']['value']:
        reasons.append('invalid_cache_subset')
    if any(r.startswith('invalid_') for r in reasons):
        for field in fields.values():
            field['complete']=False
    return fields


def provider_counts(usage,backend='claude'):
    keys=CLAUDE_KEYS if backend=='claude' else dict(input_uncached='input_tokens',cache_read='cached_input_tokens',
        cache_write='cache_write_input_tokens',output='output_tokens',reasoning_output='reasoning_output_tokens')
    result={k:usage.get(v) for k,v in keys.items() if v in usage}
    details=usage.get('output_tokens_details')
    if isinstance(details,dict) and 'thinking_tokens' in details:
        result['reasoning_output']=details['thinking_tokens']
    ttl=usage.get('cache_creation')
    if isinstance(ttl,dict):
        for key,src in (('cache_write_5m','ephemeral_5m_input_tokens'),('cache_write_1h','ephemeral_1h_input_tokens')):
            if src in ttl:
                result[key]=ttl[src]
    return result


def native_counts(value):
    """Allowlisted original field names, without renaming cached-inclusive input."""
    keys={'input_tokens','output_tokens','cached_input_tokens','cache_read_input_tokens',
        'cache_creation_input_tokens','cache_write_input_tokens','reasoning_output_tokens',
        'tokens_in','tokens_cached_in','tokens_cache_write_in','tokens_out','tokens_reasoning_out'}
    result={k:number(value[k]) for k in sorted(keys) if k in value}
    for parent,children in (('cache_creation',('ephemeral_5m_input_tokens','ephemeral_1h_input_tokens')),
                            ('output_tokens_details',('thinking_tokens',))):
        if isinstance(value.get(parent),dict):
            result[parent]={k:number(value[parent][k]) for k in children if k in value[parent]}
    return result


def read_records(path):
    try:
        text=Path(path).read_bytes().decode('utf-8')
    except (OSError,UnicodeError):
        return [],['source_unavailable']
    records=[]; bad=False
    for i,line in enumerate(source_lines(text)):
        if not line.strip():
            continue
        try:
            row=read_json(line)
            if not isinstance(row,dict):
                raise ValueError()
            records.append((i,row))
        except ValueError:
            bad=True
    return records,['capture_damaged'] if bad else []


def identity(row):
    dispatch,attempt=row.get('dispatch_id'),row.get('attempt_id')
    return ('attempt',dispatch,attempt) if isinstance(dispatch,str) and dispatch and isinstance(attempt,str) and attempt else None


def select_equal(row,selector,keys):
    return all(key not in selector or row.get(key)==selector[key] for key in keys)


def combine_messages(raws,complete,reasons):
    """Required missing fields remain missing across distinct logical messages."""
    keys=set().union(*(r.keys() for r in raws)) if raws else set()
    if any(value is not None and number(value) is None for raw in raws for value in raw.values()):
        reasons.append('invalid_count')
    return {k:sum(r[k] for r in raws) if all(number(r.get(k)) is not None for r in raws) else None for k in keys}


def adapt_receipt(out,records,selector,related):
    if not isinstance(selector.get('dispatch_id'),str) or not selector['dispatch_id']:
        out['reasons'].append('selector_missing'); return
    receipts=[r for _,r in records if r.get('kind')=='dispatch-run-receipt']
    for r in receipts:
        ident=identity(r)
        if related and all(r.get(k)==v for k,v in related.items()):
            if ident:
                out['_related'].add(ident)
            else:
                out['_related_unknown']=True
                out['reasons'].append('related_identity_missing')
    chosen=[r for r in receipts if select_equal(r,selector,('dispatch_id','attempt_id'))]
    ids={identity(r) for r in chosen}
    if not chosen:
        out['reasons'].append('selection_empty'); return
    if None in ids or len(ids)!=1:
        out['reasons'].append('ambiguous_attempt_selection'); return
    ident=next(iter(ids)); out['_coverage'].add(ident); out['_listed'].add(ident)
    if len({canonical_json(r) for r in chosen})!=1:
        out['reasons'].append('duplicate_receipt_conflict'); return
    row=chosen[-1]
    if row.get('schema_version')!=1:
        out['reasons'].append('schema_unsupported'); return
    status=row.get('usage_status')
    out['usage_status']=status if status in ('complete','partial','unavailable') else 'unknown'
    if out['usage_status']=='unknown':
        out['reasons'].append('legacy_usage_status_unknown')
    out.update(basis=row.get('usage_basis') if row.get('usage_basis') in ('codex-input-includes-cached','claude-input-excludes-cache') else None,
        requested_model=model(row.get('model')),requested_effort=effort(row.get('effort')),lifecycle=state(row.get('outcome')))
    raw={k:row[v] for k,v in RECEIPT_KEYS.items() if v in row}
    out['raw_counts']=[native_counts(row)]
    if out['basis']=='codex-input-includes-cached' or row.get('backend')=='codex':
        out['reasons'].append('usage_scope_unknown')
        # This gate follows the accounting basis even if backend metadata is
        # missing or inconsistent. Ambient receipt.session_id is never a join.
        return
    if status=='unavailable':
        out['reasons'].append('usage_unavailable'); return
    # Older Claude adapters may have supplied these zeros for absent fields.
    if row.get('backend')=='claude':
        for key in list(raw):
            if raw[key]==0:
                raw[key]=None; out['reasons'].append('legacy_zero_uncertain')
    if row.get('parent_tool_use_id') or row.get('includes_subagents'):
        out['reasons'].append('parent_scope_unknown')
    complete=status=='complete' and not (set(out['reasons'])-{'related_identity_missing'})
    out['usage']=normalize(raw,out['basis'],complete,out['reasons'])
    for field in out['usage'].values():
        if field['value'] is not None:
            field['quality']='derived'


def adapt_assistant(out,records,selector):
    session=selector.get('session_id'); selected=selector.get('message_ids')
    if not isinstance(session,str) or not isinstance(selected,list) or not selected or not all(isinstance(i,str) and i for i in selected):
        out['reasons'].append('selector_missing'); return
    rows=[r for _,r in records if r.get('type')=='assistant' and r.get('sessionId',r.get('session_id'))==session]
    request_map={}; message_map={}
    for row in rows:
        msg=row.get('message',{}); mid=msg.get('id') if isinstance(msg,dict) else None; rid=row.get('requestId')
        if mid and rid:
            request_map.setdefault(rid,set()).add(mid); message_map.setdefault(mid,set()).add(rid)
    if any(len(ids)>1 for ids in list(request_map.values())+list(message_map.values())):
        out['reasons'].append('message_identity_conflict'); return
    latest={}
    for row in rows:
        msg=row.get('message',{})
        if not isinstance(msg,dict):
            continue
        rid=row.get('requestId'); mid=msg.get('id')
        key=mid or next(iter(request_map.get(rid,[])),None) or rid
        if key and (key in selected or rid in selected):
            latest[key]=row
    if not latest or any(not any(i in (key,row.get('requestId')) for key,row in latest.items()) for i in selected):
        out['reasons'].append('selection_incomplete')
    raws=[]; models=set()
    for key,row in latest.items():
        out['_coverage'].add(('message',session,key)); out['_sessions'].add(session)
        if row.get('parent_tool_use_id'):
            out['reasons'].append('parent_scope_unknown')
        msg=row['message']; usage=msg.get('usage')
        if not isinstance(usage,dict):
            usage={}; out['reasons'].append('usage_missing')
        out['raw_counts'].append(native_counts(usage))
        raws.append(provider_counts(usage)); models.add(model(msg.get('model')))
    if len(models)==1:
        out['actual_model']=next(iter(models))
    elif models:
        out['reasons'].append('model_conflict')
    out.update(basis='claude-input-excludes-cache',usage_status='partial' if out['reasons'] else 'complete')
    out['usage']=normalize(combine_messages(raws,False,out['reasons']),out['basis'],bool(raws) and not out['reasons'],out['reasons'])
    if out['reasons']:
        out['usage_status']='partial'


def adapt_codex(out,records,selector):
    session=selector.get('session_id'); indices=selector.get('record_indices')
    if not isinstance(session,str) or not isinstance(indices,list) or not indices or not all(type(i) is int and i>=0 for i in indices):
        out['reasons'].append('selector_missing'); return
    active=None; chosen=[]; session_turns=0; started=0; failed=False; bindings=0; later_start=False
    for i,row in records:
        if row.get('type')=='thread.started':
            active=row.get('thread_id')
            bindings+=active==session
        if active==session:
            later_start=later_start or row.get('type')=='turn.started' and session_turns>0
            started+=row.get('type')=='turn.started'
            failed=failed or row.get('type') in ('turn.failed','turn.error','error')
        if row.get('type')=='turn.completed' and active==session:
            session_turns+=1
        if i in indices and row.get('type')=='turn.completed' and active==session:
            chosen.append((i,row))
    if len(chosen)!=len(set(indices)):
        out['reasons'].append('selection_incomplete')
    out['basis']='codex-input-includes-cached'
    raws=[]
    for i,row in chosen:
        usage=row.get('usage')
        raws.append(provider_counts(usage,'codex') if isinstance(usage,dict) else {})
        out['raw_counts'].append(native_counts(usage) if isinstance(usage,dict) else {})
        out['_coverage'].add(('codex-turn',session,i)); out['_sessions'].add(session)
    if len(raws)!=1 or session_turns!=1 or started>1 or failed or bindings>1 or later_start:
        out['reasons'].append('usage_scope_unknown')
        out['usage_status']='partial'; return
    out['usage_status']='partial' if out['reasons'] else 'complete'
    out['usage']=normalize(raws[0],out['basis'],not out['reasons'],out['reasons'])


def adapt_cumulative(out,records,selector,terminal_result=False):
    if terminal_result:
        session=selector.get('session_id'); indices=selector.get('record_indices')
        if not isinstance(session,str) or not isinstance(indices,list) or not indices or not all(type(i) is int and i>=0 for i in indices):
            out['reasons'].append('selector_missing'); return
        chosen=[r for i,r in records if i in indices and r.get('type')=='result' and r.get('session_id')==session]
        if len(chosen)!=1:
            out['reasons'].append('ambiguous_terminal_selection'); return
        row=chosen[-1]; usage=row.get('usage',{})
        complete=not row.get('is_error',False)
        coverage=('terminal',session)
        if row.get('modelUsage'):
            out['reasons'].append('parent_scope_unknown')
    else:
        inv=selector.get('invocation_id'); dispatch=selector.get('dispatch_id')
        if not isinstance(inv,str) or not inv or not isinstance(dispatch,str) or not dispatch:
            out['reasons'].append('selector_missing'); return
        chosen=[r for _,r in records if r.get('type')=='usage.cumulative' and r.get('invocation_id')==inv and r.get('dispatch_id')==dispatch]
        if not chosen:
            out['reasons'].append('selection_empty'); return
        if any(r.get('schema_version')!=1 for r in chosen):
            out['reasons'].append('schema_unsupported'); return
        models={model(r.get('model_identity')) for r in chosen if r.get('model_identity')}
        if len(models)>1:
            out['reasons'].append('model_identity_conflict')
        sessions={r.get('session_id') for r in chosen}
        if len(sessions)!=1 or not isinstance(next(iter(sessions)),str):
            out['reasons'].append('session_identity_conflict'); return
        session=next(iter(sessions)); row=chosen[-1]; usage=row
        seen={}; last=None
        for rec in chosen:
            seq=number(rec.get('sequence'))
            if seq is None or seq in seen and canonical_json(rec)!=seen[seq]:
                out['reasons'].append('cumulative_sequence_conflict')
            if seq is not None:
                seen[seq]=canonical_json(rec)
            raw=provider_counts(rec)
            if last is not None and any(number(raw.get(k)) is not None and number(last.get(k)) is not None and raw[k]<last[k] for k in raw):
                out['reasons'].append('cumulative_counter_regression')
            last=raw
        complete=row.get('terminal') is True and row.get('complete') is True
        coverage=('cumulative',session,inv)
    if not isinstance(usage,dict):
        usage={}; complete=False
    out['_coverage'].add(coverage); out['_sessions'].add(session); out['_whole_sessions'].add(session)
    out.update(basis='claude-input-excludes-cache',actual_model=model(row.get('model_identity')),
        requested_model=model(row.get('requested_identity')),lifecycle=state(row.get('status')),
        usage_status='complete' if complete else 'partial')
    if row.get('parent_tool_use_id') or row.get('includes_subagents'):
        out['reasons'].append('parent_scope_unknown')
    if 'model_identity_conflict' in out['reasons']:
        out['actual_model']=None
    raw=provider_counts(usage)
    out['raw_counts']=[native_counts(usage)]
    out['usage']=normalize(raw,out['basis'],complete and not out['reasons'],out['reasons'])


def adapt(source,directory):
    out=observation(source['source_id'],source['format'])
    out['_provider_binding']=source.get('provider_session_id')
    records,reasons=read_records(directory/source['path']); out['reasons'].extend(reasons)
    selector=source.get('selector',{})
    fmt=source['format']
    selector_keys={'clavain-receipt-v1':{'dispatch_id','attempt_id'},
        'claude-assistant-v1':{'session_id','message_ids'},'codex-events-v1':{'session_id','record_indices'},
        'claude-cumulative-v1':{'dispatch_id','invocation_id'},'claude-result-v1':{'session_id','record_indices'}}
    if fmt in selector_keys and set(selector)-selector_keys[fmt]:
        out['reasons'].append('selector_unsupported'); return out
    try:
        if fmt=='clavain-receipt-v1':
            adapt_receipt(out,records,selector,source.get('related_selector'))
        elif fmt=='claude-assistant-v1':
            adapt_assistant(out,records,selector)
        elif fmt=='codex-events-v1':
            adapt_codex(out,records,selector)
        elif fmt in ('claude-cumulative-v1','claude-result-v1'):
            adapt_cumulative(out,records,selector,terminal_result=fmt=='claude-result-v1')
        else:
            out['reasons'].append('format_unsupported')
    except (ValueError,TypeError,KeyError,AttributeError):
        out['reasons'].append('malformed_usage_record')
    if {'capture_damaged','malformed_usage_record'} & set(out['reasons']):
        for f in out['usage'].values():
            f['complete']=False
    out['complete']=all(out['usage'][k]['complete'] for k in REQUIRED)
    out['reasons']=sorted(set(out['reasons']))
    return out
