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


def source_lines(text):
    """Physical source lines end only at LF; preserve exact bytes/characters."""
    return re.findall(r'[^\n]*\n|[^\n]+$', text)


def markdown_regions(text, diagnostics=None):
    """Character classes: prose, code, excluded. Offsets always address original text."""
    mask = ['prose'] * len(text)
    lines = source_lines(text)
    offset, fence, comment = 0, None, False
    comment_open, comment_block, comment_multiline = None, False, False
    front_end = None
    if lines and lines[0].rstrip('\r\n') == '---':
        front_end = next((i for i,line in enumerate(lines[1:],1)
                          if line.rstrip('\r\n') in ('---','...')),None)
        if front_end is None and diagnostics is not None:
            diagnostics.append(dict(code='unclosed_frontmatter',count=1,spans=[span(text,0,len(lines[0]))]))
    list_content_indents = []
    for n, line in enumerate(lines):
        stripped = line.rstrip('\r\n')
        kind = 'prose'
        if front_end is not None and n <= front_end:
            kind = 'excluded'
        elif fence:
            kind = 'code'
            closing = re.fullmatch(r'([ \t]*)' + re.escape(fence[0]) + '{' + str(fence[1]) + r',}[ \t]*',stripped)
            if closing and fence[2] <= len(closing[1].expandtabs(4)) <= fence[2]+3:
                fence = None
        elif not comment:
            indent_text = re.match(r'[ \t]*',stripped)[0]
            indent = len(indent_text.expandtabs(4))
            if stripped.strip():
                while list_content_indents and indent < list_content_indents[-1]:
                    list_content_indents.pop()
            content_indent = list_content_indents[-1] if list_content_indents else 0
            relative = stripped[len(indent_text):]
            opening = re.match(r'(`{3,}|~{3,})',relative) if 0 <= indent-content_indent <= 3 else None
            if opening:
                fence = (opening[1][0], len(opening[1]), content_indent)
                kind = 'code'
            elif re.fullmatch(r'(?:\*[ \t]*){3,}|(?:_[ \t]*){3,}|(?:-[ \t]*){3,}',relative) and 0 <= indent-content_indent <= 3:
                # The indentation pass already popped to this block's container.
                # A break (or Setext underline) is not a new list marker and must
                # retain its enclosing list; a column-zero block already popped it.
                pass
            else:
                marker = re.match(r'(?:[-*+]|\d+[.)])[ \t]+',stripped[len(indent_text):])
                if stripped.strip():
                    is_code = indent >= content_indent+4
                    if marker and not is_code:
                        list_content_indents.append(indent+len(marker[0]))
                    elif is_code:
                        kind = 'code'
        mask[offset:offset+len(line)] = [kind]*len(line)
        if kind == 'prose':
            cursor = 0
            while cursor < len(line):
                # An active comment owns its contents, including indentation and ticks.
                if comment or line.startswith('<!--',cursor):
                    if not comment:
                        comment_open = offset+cursor
                        comment_block = not line[:cursor].strip(' \t')
                        comment_multiline = False
                    end = line.find('-->',cursor+(0 if comment else 4))
                    stop = len(line) if end < 0 or comment_block else end+3
                    mask[offset+cursor:offset+stop] = ['excluded']*(stop-cursor)
                    comment = end < 0
                    if not comment_block and end < 0 and not comment_multiline:
                        comment_multiline = True
                        if diagnostics is not None:
                            diagnostics.append(dict(code='multiline_inline_comment',count=1,spans=[span(text,comment_open,comment_open+4)]))
                    cursor = stop
                elif line[cursor] == '`':
                    run = re.match(r'`+',line[cursor:])[0]
                    close = re.search(r'(?<!`)'+re.escape(run)+r'(?!`)',line[cursor+len(run):])
                    if close:
                        stop = cursor+len(run)+close.end()
                        mask[offset+cursor:offset+stop] = ['code']*(stop-cursor)
                        cursor = stop
                    else:
                        cursor += len(run)
                else:
                    cursor += 1
        offset += len(line)
    if comment and diagnostics is not None:
        diagnostics.append(dict(code='unclosed_comment',count=1,spans=[span(text,comment_open,comment_open+4)]))
    return mask


def span(text, start, end):
    def point(offset):
        return text.count('\n', 0, offset)+1, offset-text.rfind('\n', 0, offset)
    sl,sc = point(start)
    el,ec = point(end)
    return dict(start_line=sl,start_column=sc,end_line=el,end_column=ec)


def line_offsets(text):
    offsets = [0]
    for line in source_lines(text):
        offsets.append(offsets[-1]+len(line))
    return offsets
