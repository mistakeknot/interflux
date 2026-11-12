#!/usr/bin/env python3
"""Check source presence, never semantic support. Inputs are immutable snapshots."""
from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path

from _review_evidence import (PARSER_VERSION, canonical_json, digest, document_id,
    line_offsets, load_findings, markdown_regions, parser_hash, read_json, seal_index, source_lines, span)


def redaction_marker():
    path = Path(__file__).resolve().parents[1]/'hooks/redact-melange-write.py'
    spec = importlib.util.spec_from_file_location('review_redactor', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MARKER


def normalized(text, offset=0):
    chars, positions = [], []
    quotes = str.maketrans('‘’“”', "''\"\"")
    for i,c in enumerate(text):
        c = c.translate(quotes)
        if c in ' \t\r\n\f\v':
            if chars and chars[-1] == ' ':
                positions[-1] = (positions[-1][0],offset+i+1)
                continue
            c = ' '
        chars.append(c)
        positions.append((offset+i,offset+i+1))
    return ''.join(chars), positions


def occurrences(source, needle):
    start = 0
    while needle:
        at = source.find(needle, start)
        if at < 0:
            return
        yield at, at+len(needle)
        start = at+1


def matches(text, quote, start, end, regions):
    literal = [(a+start,b+start) for a,b in occurrences(text[start:end], quote)]
    if literal:
        return literal, 'literal'
    # A normalized search is confined to each contiguous prose segment.
    q, _ = normalized(quote)
    found = []
    cursor = start
    while cursor < end:
        stop = cursor+1
        while stop < end and regions[stop] == regions[cursor]:
            stop += 1
        if regions[cursor] == 'prose':
            source, positions = normalized(text[cursor:stop], cursor)
            found.extend((positions[a][0],positions[b-1][1]) for a,b in occurrences(source,q))
        cursor = stop
    return found, 'normalized'


def drop_emphasis(text):
    # Only balanced, non-whitespace-bounded **strong**, __strong__, *em*, _em_.
    for delimiter in ('**', '__', '*', '_'):
        d = re.escape(delimiter)
        text = re.sub(r'(?<!\w)'+d+r'(?=\S)(.+?)(?<=\S)'+d+r'(?!\w)', r'\1', text)
    return text


def markup_matches(text, quote, start, end, regions):
    """Diagnostic-only emphasis removal, preserving original character positions."""
    query = normalized(drop_emphasis(quote))[0]
    found = []
    cursor = start
    while cursor < end:
        stop = cursor+1
        while stop < end and regions[stop] == regions[cursor]:
            stop += 1
        if regions[cursor] == 'prose':
            chars = [(c,cursor+i) for i,c in enumerate(text[cursor:stop])]
            for delimiter in ('**','__','*','_'):
                d = re.escape(delimiter)
                pattern = r'(?<!\w)'+d+r'(?=\S)(.+?)(?<=\S)'+d+r'(?!\w)'
                remove = set()
                for m in re.finditer(pattern,''.join(c for c,_ in chars)):
                    remove.update(range(m.start(),m.start()+len(delimiter)))
                    remove.update(range(m.end()-len(delimiter),m.end()))
                chars = [p for i,p in enumerate(chars) if i not in remove]
            value, positions = normalized(''.join(c for c,_ in chars))
            found.extend((chars[positions[a][0]][1],chars[positions[b-1][1]-1][1]+1)
                         for a,b in occurrences(value,query))
        cursor = stop
    return found


def parse_location(value):
    """Canonical path plus line range; uncertain forms remain unparseable."""
    m = re.fullmatch(r'([^:\n]+):(\d+)(?::(\d+))?(?:-(\d+)(?::(\d+))?)?',value)
    if not m:
        return None
    try:
        path = document_id(m[1])
    except ValueError:
        return None
    first,last = int(m[2]),int(m[4] or m[2])
    if first < 1 or last < first or any(int(m[k])<1 for k in (3,5) if m[k]):
        return None
    return path,first,last


def target_spelling(value, doc_id):
    canonical = document_id(value)
    # The index identifies one document. A bare basename is an unambiguous alias
    # within this invocation; paths with other directories remain distinct.
    return doc_id if canonical == doc_id.rsplit('/',1)[-1] else canonical


def prefix_uncertain(value, doc_id):
    """A suffix at a directory boundary is evidence of possible identity only."""
    return value != doc_id and (value.endswith('/'+doc_id) or doc_id.endswith('/'+value))


def check_document(data, doc_id, expected, index, rows, input_mode='snapshot'):
    base = dict(schema_version=1, document_id=doc_id, document_sha256=digest(data), results=[], findings=[])
    failures = []
    try:
        canonical_id = document_id(doc_id)
        if canonical_id != doc_id or index.get('document_id') != doc_id:
            failures.append('document_identity_mismatch')
        if digest(data) != expected or index.get('document_sha256') != expected:
            failures.append('document_hash_mismatch')
        if index.get('index_sha256') != seal_index(index)['index_sha256']:
            failures.append('index_hash_mismatch')
        if index.get('schema_version') != 1 or index.get('parser_version') != PARSER_VERSION or index.get('parser_sha256') != parser_hash():
            failures.append('parser_contract_mismatch')
        findings, provenance = load_findings(rows, input_mode)
        text = data.decode('utf-8')
        nlines = len(source_lines(text))
        for s in index['sections']:
            if not isinstance(s['section_id'],str) or not s['section_id']:
                raise ValueError('invalid_section')
            for key in ('line_range','subtree_line_range'):
                r = s[key]
                if type(r['start']) is not int or type(r['end']) is not int or not (1 <= r['start'] <= nlines+1 and r['start']-1 <= r['end'] <= nlines):
                    raise ValueError('invalid_section_range')
    except (ValueError, KeyError, TypeError, AttributeError):
        failures.append('invalid_structural_input')
    if failures:
        return dict(base, run_status='invalid_snapshot', reasons=sorted(set(failures))), 2
    base.update(run_status='complete',index_sha256=index['index_sha256'], row_diagnostics=provenance)
    regions, offsets, marker = markdown_regions(text), line_offsets(text), redaction_marker()
    sections = {}
    for section in index['sections']:
        sections.setdefault(section['section_id'], []).append(section)
    def bounds(section, key='line_range'):
        r = section[key]
        return offsets[r['start']-1], offsets[r['end']]
    for finding in findings:
        fid = finding['id']
        # Explicit document attribution wins; otherwise use the location's path.
        loc = parse_location(finding['location'])
        attributed = finding.get('document_id', loc[0] if loc else doc_id)
        try:
            attributed = target_spelling(attributed,doc_id)
        except (ValueError,AttributeError):
            attributed = None
        uncertain = attributed is not None and prefix_uncertain(attributed,doc_id)
        if attributed is not None and attributed != doc_id and not uncertain:
            base['findings'].append(dict(finding_id=fid,status='out_of_scope',quote_count=0,
                counts=dict(matched=0,mismatched=0,unverifiable=0),complete=True,support='unverified'))
            continue
        quote = finding.get('quote')
        if quote is None:
            members = [(None,None,'missing','absent')]
        elif isinstance(quote,dict):
            members = [(0,quote,None,None)]
        elif isinstance(quote,list) and quote:
            members = [(i,q,None,None) for i,q in enumerate(quote)]
        else:
            members = [(None,None,'unverifiable','invalid_quote_container')]
        results = []
        for qi,q,status,reason in members:
            result = dict(finding_id=fid,quote_index=qi,section_id=q.get('section_id') if isinstance(q,dict) else None,
                status=status,reason=reason,match_mode=None,spans=[],diagnostics=[],support='unverified',occurrence_ambiguous=False)
            if uncertain or loc and prefix_uncertain(target_spelling(loc[0],doc_id),doc_id):
                result['diagnostics'].append(dict(code='location_uncertain',count=1,spans=[]))
            def fail(why):
                result.update(status='unverifiable',reason=why)
            if status is None:
                if not isinstance(q,dict) or not all(isinstance(q.get(k),str) and q[k].strip() for k in ('section_id','text')):
                    fail('invalid_quote')
                elif marker in q['text']:
                    fail('redacted')
                elif 'provenance' in q and (not isinstance(q['provenance'],dict) or q['provenance'].get('text_state') not in ('original','transformed','unknown')):
                    fail('invalid_provenance')
                elif q.get('provenance',{}).get('text_state') == 'transformed':
                    fail('transformed')
                elif (finding.get('source_type') == 'imported' or isinstance(finding.get('source'),dict) and 'import' in finding['source']) and q.get('provenance',{}).get('text_state') != 'original':
                    fail('transformation_unknown')
                elif q.get('provenance',{}).get('text_state') == 'unknown':
                    fail('transformation_unknown')
                elif len(sections.get(q['section_id'],[])) != 1:
                    fail('ambiguous_section' if sections.get(q['section_id']) else 'unknown_section')
                else:
                    section = sections[q['section_id']][0]
                    start,end = bounds(section)
                    found, mode = matches(text,q['text'],start,end,regions)
                    redacted_spans = list(occurrences(text,marker))
                    if any(a < y and x < b for a,b in found for x,y in redacted_spans):
                        fail('redacted')
                    elif found:
                        result.update(status='matched',reason=mode,match_mode=mode,
                            spans=[span(text,a,b) for a,b in found], occurrence_ambiguous=len(found)>1)
                    elif any(x in q['text'] for x in ('...', '…', '[…]')):
                        fail('elision_ambiguous')
                    else:
                        result.update(status='mismatched',reason='not_present')
                        for other in index['sections']:
                            a,b = bounds(other)
                            hits,_ = matches(text,q['text'],a,b,regions)
                            if hits and a > start and a < bounds(section,'subtree_line_range')[1]:
                                result['diagnostics'].append(dict(code='present_in_descendant',count=len(hits),spans=[span(text,x,y) for x,y in hits]))
                        whole,_ = matches(text,q['text'],0,len(text),regions)
                        crossing = [(a,b) for a,b in whole if a < start < b or a < end < b]
                        if crossing:
                            result['diagnostics'].append(dict(code='crosses_heading_boundary',count=len(crossing),spans=[span(text,a,b) for a,b in crossing]))
                        markup = markup_matches(text,q['text'],start,end,regions)
                        if markup:
                            result['diagnostics'].append(dict(code='markup_drop_match',count=len(markup),spans=[span(text,a,b) for a,b in markup]))
                    if not loc:
                        result['diagnostics'].append(dict(code='location_unparseable',count=1,spans=[]))
                    elif prefix_uncertain(target_spelling(loc[0],doc_id),doc_id):
                        pass  # The uncertainty signal above does not establish line agreement.
                    elif target_spelling(loc[0],doc_id) != doc_id:
                        result['diagnostics'].append(dict(code='location_other_document',count=1,spans=[]))
                    elif not (loc[1] <= section['line_range']['end'] and loc[2] >= section['line_range']['start']):
                        result['diagnostics'].append(dict(code='location_section_disagreement',count=1,spans=[]))
            results.append(result)
        base['results'].extend(results)
        counts = {s:sum(r['status']==s for r in results) for s in ('matched','mismatched','unverifiable')}
        rollup = next((s for s in ('missing','unverifiable','mismatched','matched') if any(r['status']==s for r in results)))
        base['findings'].append(dict(finding_id=fid,status=rollup,quote_count=0 if quote is None else len(members),
            counts=counts,complete=not counts['unverifiable'],support='unverified'))
    return base, int(any(r['status']=='unverifiable' for r in base['results']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('document','document-id','expected-sha256','index','findings'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--input-mode',choices=('snapshot','ledger'),default='snapshot')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    try:
        raw = Path(args.findings).read_text(encoding='utf-8')
        try:
            value = read_json(raw)
            rows = value['findings'] if isinstance(value,dict) and 'findings' in value else value if isinstance(value,list) else [value]
        except ValueError:
            rows = [read_json(line) for line in source_lines(raw) if line.strip()]
        report,code = check_document(Path(args.document).read_bytes(),args.document_id,args.expected_sha256,
            read_json(Path(args.index).read_text(encoding='utf-8')),rows,args.input_mode)
    except (ValueError, OSError, KeyError, TypeError):
        report,code = dict(schema_version=1,run_status='invalid_input',reasons=['invalid_input'],results=[]),2
    print(canonical_json(report).decode(),end='')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
