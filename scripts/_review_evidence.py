"""Shared, deterministic contracts for opt-in review evidence tools (v1)."""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
from pathlib import Path

PARSER_VERSION = 'markdown-sections-v1'
STAMP_FIELDS = {'status', 'convergence_refs', 'disagreement_refs', 'novelty',
                'risk', 'taste', 'taste_kind', 'cluster_id'}


def canonical_json(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_json_key')
        result[key] = value
    return result


def read_json(text):
    return json.loads(text, object_pairs_hook=unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid_number')))


def document_id(value):
    value = value.replace('\\', '/')
    if not value or '\0' in value or value.startswith('/') or re.match(r'^[A-Za-z]:', value):
        raise ValueError('invalid_document_id')
    value = posixpath.normpath(value)
    if value in ('.', '..') or value.startswith('../'):
        raise ValueError('invalid_document_id')
    return value


def parser_hash():
    root = Path(__file__).parent
    return digest(canonical_json({f'scripts/{name}': digest((root/name).read_bytes())
        for name in ('_review_evidence.py', 'markdown_section_index.py')}))


def seal_index(index):
    index = dict(index)
    index['index_sha256'] = digest(canonical_json({k:v for k,v in index.items()
        if k not in ('index_sha256', 'comparison')}))
    return index


def load_findings(rows, mode='snapshot'):
    if mode not in ('snapshot', 'ledger'):
        raise ValueError('invalid_input_mode')
    found, provenance, skipped = {}, {}, []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError('invalid_finding_row')
        kind = row.get('record_type', row.get('type'))
        if kind in ('metadata', 'event'):
            skipped.append({'row_index':i, 'reason':'non_finding'})
            continue
        if kind not in (None, 'finding') or not all(isinstance(row.get(k), str) and row[k]
                                                   for k in ('id', 'claim', 'location')):
            raise ValueError('invalid_finding_row')
        key = row['id']
        if key in found and row != found[key]:
            before, after = found[key], row
            if mode == 'snapshot' or {k:v for k,v in before.items() if k not in STAMP_FIELDS} != {
                    k:v for k,v in after.items() if k not in STAMP_FIELDS}:
                raise ValueError('immutable_finding_changed')
        found[key] = row
        provenance.setdefault(key, []).append({'row_index':i, 'sha256':digest(canonical_json(row))})
    return list(found.values()), {'skipped':skipped, 'rows':provenance,
        'duplicate_count':sum(len(v)-1 for v in provenance.values())}


def markdown_regions(text):
    """Character classes: prose, code, excluded. Offsets always address original text."""
    mask = ['prose'] * len(text)
    lines = text.splitlines(keepends=True)
    offset, fence, front, comment = 0, None, False, False
    for n, line in enumerate(lines):
        stripped = line.rstrip('\r\n')
        kind = 'prose'
        if n == 0 and stripped == '---':
            front = True
            kind = 'excluded'
        elif front:
            kind = 'excluded'
            if stripped in ('---', '...'):
                front = False
        elif fence:
            kind = 'code'
            if re.match(r'^ {0,3}' + re.escape(fence[0]) + '{' + str(fence[1]) + r',}\s*$', stripped):
                fence = None
        else:
            opening = re.match(r'^ {0,3}(`{3,}|~{3,})', stripped)
            if opening:
                fence = (opening[1][0], len(opening[1]))
                kind = 'code'
            elif stripped.startswith(('    ', '\t')):
                kind = 'code'
        mask[offset:offset+len(line)] = [kind]*len(line)
        if kind == 'prose':
            cursor = 0
            while cursor < len(line):
                start = cursor if comment else line.find('<!--', cursor)
                if start < 0:
                    break
                end = line.find('-->', start + (0 if comment else 4))
                stop = len(line) if end < 0 else end+3
                mask[offset+start:offset+stop] = ['excluded']*(stop-start)
                comment = end < 0
                cursor = stop
            for match in re.finditer(r'(`+)([^`]*?)\1(?!`)', line):
                a,b = offset+match.start(), offset+match.end()
                if all(x == 'prose' for x in mask[a:b]):
                    mask[a:b] = ['code']*(b-a)
        offset += len(line)
    return mask


def span(text, start, end):
    def point(offset):
        return text.count('\n', 0, offset)+1, offset-text.rfind('\n', 0, offset)
    sl,sc = point(start)
    el,ec = point(end)
    return dict(start_line=sl,start_column=sc,end_line=el,end_column=ec)


def line_offsets(text):
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1]+len(line))
    return offsets
