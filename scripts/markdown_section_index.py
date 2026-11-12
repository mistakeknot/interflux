#!/usr/bin/env python3
"""Produce a deterministic Markdown section index (v1). No model calls."""
from __future__ import annotations

import argparse
import collections
import math
import re
from pathlib import Path

from _review_evidence import (PARSER_VERSION, canonical_json, digest, document_id,
    line_offsets, markdown_regions, parser_hash, read_json, seal_index, span)

RECOGNIZERS = {'numbered_heading', 'section_reference', 'heading_annotation',
               'heading_status', 'relationship', 'bold_lead'}
SECTION_REF = re.compile(r'§\s*(\d+(?:\.\d+)*)(?:\s*([–—-])\s*§?\s*(\d+(?:\.\d+)*))?')


def validate_profile(profile):
    if profile is None:
        return []
    if not isinstance(profile,dict) or set(profile) != {'schema_version','id','version','rules'} or profile['schema_version'] != 1 or not isinstance(profile['id'],str) or not profile['id'] or type(profile['version']) is not int or profile['version'] < 1 or not isinstance(profile['rules'],list):
        raise ValueError('invalid_profile')
    ids = set()
    for rule in profile['rules']:
        if not isinstance(rule,dict) or not {'id','scope','recognizer'} <= set(rule):
            raise ValueError('invalid_profile_rule')
        if not isinstance(rule['id'],str) or not rule['id'] or rule['id'] in ids:
            raise ValueError('invalid_profile_rule_id')
        ids.add(rule['id'])
        recognizer = rule['recognizer']
        if recognizer not in RECOGNIZERS or rule['scope'] not in ('heading','body','all'):
            raise ValueError('invalid_recognizer')
        allowed = {'id','scope','recognizer','candidate_kind','case_sensitive'}
        if recognizer == 'numbered_heading':
            allowed.add('trailing_dot')
        if recognizer in ('heading_annotation','heading_status','relationship'):
            allowed.add('vocabulary')
            if not isinstance(rule.get('vocabulary'),list) or not rule['vocabulary'] or not all(isinstance(s,str) and s for s in rule['vocabulary']):
                raise ValueError('invalid_vocabulary')
        if set(rule)-allowed or any(type(rule[k]) is not bool for k in ('case_sensitive','trailing_dot') if k in rule):
            raise ValueError('invalid_rule_parameter')
        if 'candidate_kind' in rule and rule['candidate_kind'] not in ('ruling_candidate','status_candidate','term_candidate','relationship_candidate'):
            raise ValueError('invalid_candidate_kind')
    return profile['rules']


def build_index(data, doc_id, profile=None, previous=None):
    doc_id = document_id(doc_id)
    rules = validate_profile(profile)
    text = data.decode('utf-8')
    lines, offsets = text.splitlines(keepends=True), line_offsets(text)
    regions = markdown_regions(text)
    diagnostics, headings = [], []
    for i,line in enumerate(lines):
        start = offsets[i]
        # Heading syntax must be wholly outside comments/code/frontmatter.
        body = line.rstrip('\r\n')
        active = bool(body.strip()) and regions[start+len(body)-len(body.lstrip())] == 'prose' and 'excluded' not in regions[start:start+len(body)]
        if not active:
            continue
        atx = re.fullmatch(r' {0,3}(#{1,6})(?:[ \t]+(.*?)|[ \t]*)',body)
        if atx:
            heading = re.sub(r'[ \t]+#+[ \t]*$', '', atx[2] or '').strip()
            headings.append(dict(heading=heading,level=len(atx[1]),line=i+1,last=i+1))
        elif i+1 < len(lines) and re.fullmatch(r' {0,3}(=+|-+)\s*',lines[i+1]) and all(r=='prose' for r in regions[offsets[i+1]:offsets[i+2]]) and not re.match(r'\s*(?:[-*+] |>|#{1,6} )',body):
            headings.append(dict(heading=body.strip(),level=1 if lines[i+1].lstrip().startswith('=') else 2,line=i+1,last=i+2))
        elif re.match(r' {0,3}#{7,}\s',body):
            diagnostics.append(dict(code='unsupported_heading',line=i+1))
    # Underlines must not themselves become headings.
    headings = [h for h in headings if not any(o['last']==h['line'] and o['line']!=h['line'] for o in headings)]
    anchors, stack, siblings = {}, [], collections.Counter()
    sections = [dict(section_id='s-'+digest(canonical_json([doc_id,'preamble'])),heading='',number=None,
        number_raw=None,heading_path=[],parent_id=None,heading_span=None,level=0,
        line_range=dict(start=1,end=(headings[0]['line']-1 if headings else len(lines))),
        subtree_line_range=dict(start=1,end=(headings[0]['line']-1 if headings else len(lines))),
        identity_stability='heading_path')]
    for i,h in enumerate(headings):
        while stack and stack[-1]['level'] >= h['level']:
            stack.pop()
        parent = stack[-1] if stack else None
        key = (parent['section_id'] if parent else None,h['heading'])
        siblings[key] += 1
        path = (parent['heading_path'] if parent else [])+[h['heading']]
        ordinal_path = (parent['_ordinal_path'] if parent else [])+[siblings[key]]
        anchor = re.search(r'\s*\{#([^{}\s]+)\}$',h['heading'])
        identity = dict(document_id=doc_id,anchor=anchor[1]) if anchor else dict(document_id=doc_id,path=path,ordinals=ordinal_path)
        sid = 's-'+digest(canonical_json(identity))
        if anchor:
            if anchor[1] in anchors:
                raise ValueError('duplicate_anchor')
            anchors[anchor[1]] = sid
        number = raw = None
        nrule = next((r for r in rules if r['recognizer']=='numbered_heading'),None)
        pattern = r'^(\d+(?:\.\d+)*)(\.)?(?=\s|$)' if nrule and nrule.get('trailing_dot') else r'^(\d+(?:\.\d+)*)(?=\s|$)'
        nm = re.match(pattern,h['heading'])
        if nm:
            number,raw = nm[1],nm[0]
        end = headings[i+1]['line']-1 if i+1 < len(headings) else len(lines)
        subtree_end = next((o['line']-1 for o in headings[i+1:] if o['level']<=h['level']),len(lines))
        section = dict(section_id=sid,heading=h['heading'],number=number,number_raw=raw,heading_path=path,
            parent_id=parent['section_id'] if parent else None,heading_span=dict(start_line=h['line'],end_line=h['last']),
            line_range=dict(start=h['line'],end=end),subtree_line_range=dict(start=h['line'],end=subtree_end),
            identity_stability='explicit_anchor' if anchor else 'heading_path',level=h['level'],
            _ordinal_path=ordinal_path,_sibling_key=key,_anchor=bool(anchor))
        sections.append(section)
        stack.append(section)
    unstable = set()
    for s in sections[1:]:
        if siblings[s['_sibling_key']] > 1 or s['parent_id'] in unstable:
            if not s['_anchor']:
                s['identity_stability'] = 'snapshot_only'
                unstable.add(s['section_id'])
    owners = {}
    for s in sections:
        r = s['line_range']
        body = ''.join(lines[r['start']-1:r['end']])
        s['content_sha256'] = digest(body.encode())
        s['token_estimate'] = dict(value=math.ceil(len(body)/4),method='ceil-unicode-chars/4')
        for n in range(r['start'],r['end']+1):
            owners[n] = s
        for key in list(s):
            if key.startswith('_'):
                del s[key]
    definitions, candidates, references = [], [], []
    def record(kind,key,rule,start,end,label_start=None,label_end=None):
        line = text.count('\n',0,start)+1
        return dict(kind=kind,key=key,rule_id=rule,section_id=owners[line]['section_id'],
            label_span=span(text,label_start if label_start is not None else start,label_end if label_end is not None else end),
            span=span(text,start,end))
    def visible(match, offset=0):
        return all(x=='prose' for x in regions[offset+match.start():offset+match.end()])
    for s in sections[1:]:
        m = re.match(r'^(Ruling|Term)\s+(.+?)(?:\s*\{#.*\})?$',s['heading'])
        if m:
            a = offsets[s['heading_span']['start_line']-1]
            definitions.append(record(m[1].lower(),m[2],'generic-heading',a,offsets[s['heading_span']['end_line']]))
    for m in re.finditer(r'\*\*(Ruling|Term)\s+([^:\n]+):\*\*[^\n]*',text):
        if visible(m):
            definitions.append(record(m[1].lower(),m[2],'generic-declaration',m.start(),m.end(),m.start(2),m.end(2)))
    for m in re.finditer(r'^ {0,3}\[([^]\n]+)\]:\s*(\S+)[^\n]*',text,re.M):
        if visible(m):
            d = record('link',m[1].strip().casefold(),'generic-link-definition',m.start(),m.end(),m.start(1),m.end(1))
            d['target'] = m[2]
            definitions.append(d)
    for pattern,kind in ((r'\[\[(ruling|term):([^]\n]+)\]\]','named'),
                         (r'\[[^]\n]*\]\(([^)\s]+)\)','link'),
                         (r'\[[^]\n]+\]\[([^]\n]+)\]','reference_link')):
        for m in re.finditer(pattern,text):
            if visible(m):
                key = m[2] if kind=='named' else m[1]
                references.append(record(m[1] if kind=='named' else kind,key,'generic-reference',m.start(),m.end()))
    for rule in rules:
        recognizer = rule['recognizer']
        flags = 0 if rule.get('case_sensitive',True) else re.I
        for n,line in enumerate(lines,1):
            owner = owners[n]
            heading = owner['heading_span'] is not None and owner['heading_span']['start_line'] <= n <= owner['heading_span']['end_line']
            if (rule['scope']=='heading' and not heading) or (rule['scope']=='body' and heading):
                continue
            off = offsets[n-1]
            def candidate(kind,key,m):
                c = record(rule.get('candidate_kind',kind),key,rule['id'],off+m.start(),off+m.end())
                candidates.append(c)
                return c
            if recognizer == 'section_reference':
                for m in SECTION_REF.finditer(line):
                    if visible(m,off):
                        r = record('section',m[1],rule['id'],off+m.start(),off+m.end())
                        if m[3]:
                            r['range_end'] = m[3]
                        references.append(r)
            elif recognizer == 'bold_lead':
                m = re.match(r'^\s*(?:[-*+]\s+)?\*\*([^*\n]+?):?\*\*[^\n]*',line)
                if m and all(x=='prose' for x in regions[off+m.start(1):off+m.end(1)]):
                    c = candidate('term_candidate',m[1].rstrip(':'),m)
                    c['label_span'] = span(text,off+m.start(1),off+m.end(1))
                elif re.match(r'^\s*(?:[-*+]\s+)?\*\*',line):
                    diagnostics.append(dict(code='unsupported_bold_lead',line=n,rule_id=rule['id']))
            elif recognizer in ('relationship','heading_status','heading_annotation'):
                accepted = []
                for word in sorted(rule['vocabulary'],key=lambda w:(-len(w),w)):
                    for m in re.finditer(r'(?<!\w)'+re.escape(word)+r'(?!\w)',line,flags):
                        if not visible(m,off) or any(m.start()<b and a<m.end() for a,b in accepted):
                            continue
                        if recognizer == 'heading_status':
                            emphasized = any(e.start(2)<=m.start() and m.end()<=e.end(2) for e in re.finditer(r'(\*\*|__|\*|_)(\S(?:.*?\S)?)\1',line))
                            if not emphasized:
                                continue
                        accepted.append((m.start(),m.end()))
                        kind = {'relationship':'relationship_candidate','heading_status':'status_candidate','heading_annotation':'ruling_candidate'}[recognizer]
                        c = candidate(kind,word,m)
                        if recognizer == 'relationship':
                            c['relation'] = word.lower().replace('-','_').replace(' ','_')
                            # Allowed gap: whitespace and balanced/unbalanced closing emphasis,
                            # colon/comma punctuation. Target lists use comma/and/or plus §.
                            tail = line[m.end():]
                            gap = re.match(r'[ \t:*_]*',tail).end()
                            target_text = tail[gap:]
                            targets = []
                            cursor = 0
                            while True:
                                target = SECTION_REF.match(target_text,cursor)
                                if not target:
                                    break
                                t = dict(number=target[1],span=span(text,off+m.end()+gap+target.start(),off+m.end()+gap+target.end()))
                                if target[3]:
                                    t.update(range_end=target[3],resolution='range_unexpanded')
                                targets.append(t)
                                sep = re.match(r'(?:\s*,\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+)',target_text[target.end():],re.I)
                                if not sep:
                                    break
                                cursor = target.end()+sep.end()
                            c.update(targets=targets,resolution='candidate' if targets else 'no_target')
                        elif recognizer == 'heading_annotation':
                            value = re.match(r'[ \t:]+([^\n,;]+)',line[m.end():])
                            c['value'] = value[1].strip() if value else None
    numbers = collections.defaultdict(list)
    for s in sections:
        if s['number'] is not None:
            numbers[s['number']].append(s['section_id'])
    def resolve(ids):
        return dict(resolution='resolved' if len(ids)==1 else 'ambiguous' if ids else 'unresolved',target_section_ids=sorted(ids))
    def link_target(key):
        if key.startswith('#'):
            return resolve([anchors[key[1:]]] if key[1:] in anchors else [])
        return dict(resolution='external',target_section_ids=[])
    for r in references:
        kind,key = r['kind'],r['key']
        if kind == 'section':
            r.update(dict(resolution='range_unexpanded',target_section_ids=[]) if r.get('range_end') else resolve(numbers[key]))
        elif kind == 'link':
            r.update(link_target(key))
        elif kind == 'reference_link':
            defs = [d for d in definitions if d['kind']=='link' and d['key']==key.strip().casefold()]
            r.update(link_target(defs[0]['target']) if len(defs)==1 else resolve([d['section_id'] for d in defs]))
        else:
            r.update(resolve([d['section_id'] for d in definitions if d['kind']==kind and d['key']==key]))
    for c in candidates:
        for t in c.get('targets',[]):
            if not t.get('range_end'):
                t.update(resolve(numbers[t['number']]))
    for number, ids in numbers.items():
        if len(ids)>1:
            diagnostics.append(dict(code='duplicate_number',number=number,count=len(ids)))
    result = dict(schema_version=1,document_id=doc_id,document_sha256=digest(data),parser_version=PARSER_VERSION,
        parser_sha256=parser_hash(),syntax_profile=None if profile is None else dict(id=profile['id'],version=profile['version'],sha256=digest(canonical_json(profile))),
        sections=sections,definitions=definitions,candidates=candidates,references=references,diagnostics=diagnostics)
    if previous is not None:
        if previous.get('document_id') != doc_id or previous.get('index_sha256') != seal_index(previous)['index_sha256']:
            raise ValueError('invalid_previous_index')
        old = {s['section_id']:s for s in previous['sections']}
        new = {s['section_id']:s for s in sections}
        result['comparison'] = dict(retained=sorted(old.keys() & new.keys()),added=sorted(new.keys()-old.keys()),
            removed=sorted(old.keys()-new.keys()),content_changed=sorted(k for k in old.keys() & new.keys() if old[k]['content_sha256'] != new[k]['content_sha256']),
            duplicate_ambiguity=sorted(unstable))
    return seal_index(result)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('document')
    p.add_argument('--document-id',required=True)
    p.add_argument('--syntax-profile')
    p.add_argument('--previous')
    p.add_argument('--json',action='store_true')
    args = p.parse_args()
    try:
        profile = read_json(Path(args.syntax_profile).read_text(encoding='utf-8')) if args.syntax_profile else None
        previous = read_json(Path(args.previous).read_text(encoding='utf-8')) if args.previous else None
        result = build_index(Path(args.document).read_bytes(),args.document_id,profile,previous)
    except (ValueError,OSError,KeyError,TypeError):
        print(canonical_json(dict(schema_version=1,run_status='invalid_input',reasons=['invalid_input'])).decode(),end='')
        return 2
    print(canonical_json(result).decode(),end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
