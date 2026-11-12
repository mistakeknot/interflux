"""Synthetic reproductions of the independent review's input-boundary findings."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from markdown_section_index import build_index
from check_quotes import check_document
from _review_evidence import digest, load_findings


def profile():
    return dict(schema_version=1,id='regression',version=1,rules=[
        dict(id='nums',scope='heading',recognizer='numbered_heading'),
        dict(id='refs',scope='all',recognizer='section_reference'),
        dict(id='terms',scope='body',recognizer='bold_lead'),
        dict(id='notes',scope='heading',recognizer='heading_annotation',vocabulary=['card','ruled'])])


def check(text,quote,section=1,location='docs/example.md:2'):
    data=text.encode()
    idx=build_index(data,'docs/example.md',profile())
    row=dict(id='f',claim='Synthetic',location=location,quote=dict(section_id=idx['sections'][section]['section_id'],text=quote))
    return check_document(data,'docs/example.md',digest(data),idx,[row])


@pytest.mark.parametrize('location',[
    './docs/example.md:2','docs//example.md:2','example.md:2',
    'docs/example.md:2:5','docs\\example.md:2','example.md:2:5-2:9'])
def test_p1_location_alias_checks_quote(location):
    report,code=check('# A\nactual\n','absent',location=location)
    assert code==0 and report['results'][0]['status']=='mismatched'


def test_uncertain_location_never_silently_skips_target_quote():
    report,code=check('# A\nactual\n','absent',location='../invalid:2')
    assert code==0 and report['results'][0]['status']=='mismatched'
    assert 'location_unparseable' in {d['code'] for d in report['results'][0]['diagnostics']}


@pytest.mark.parametrize('text,headings',[
    ('# A\nUse `<!--` literally.\n# B\n## C\n',['','A','B','C']),
    ('# A\n## 4.2 Recovery <!-- todo -->\n',['','A','4.2 Recovery']),
    ('<!--\n    old -->\n# Real\n',['','Real']),
    ('```md\n<!--\n```\n# Real\n',['','Real']),
    ('<!-- ` -->\n# Real\n',['','Real'])])
def test_p1_comment_code_heading_boundaries(text,headings):
    idx=build_index(text.encode(),'docs/example.md')
    assert [s['heading'] for s in idx['sections']]==headings


def test_p2_nested_list_continuation_and_real_code():
    text='# 1 Lists\n- parent\n    - nested see §2\n      **Portal:** A term.\n      continued   prose\n\n          code §88\n# 2 End\n'
    idx=build_index(text.encode(),'docs/example.md',profile())
    assert [r['key'] for r in idx['references']]==['2']
    assert any(c['key']=='Portal' for c in idx['candidates'])
    report,code=check(text,'continued prose')
    assert code==0 and report['results'][0]['match_mode']=='normalized'


@pytest.mark.parametrize('separator',['\x0c','\x85','\u2028','\r'])
def test_p2_only_newline_numbers_source_lines(separator):
    text=f'# A\na{separator}b{separator}c\n# B\n**Term X:** y\n'
    idx=build_index(text.encode(),'docs/example.md')
    b=idx['sections'][2]
    term=idx['definitions'][0]
    assert b['line_range']==dict(start=3,end=4)
    assert term['section_id']==b['section_id'] and term['span']['start_line']==4


@pytest.mark.parametrize('quote,section',[('beta\n# B',2),('beta\n# B',1)])
def test_p2_diagnostics_cross_both_heading_boundaries(quote,section):
    report,_=check('# A\nbeta\n# B\ngamma\n',quote,section)
    diagnostic=next(d for d in report['results'][0]['diagnostics'] if d['code']=='crosses_heading_boundary')
    assert diagnostic['count']==len(diagnostic['spans'])==1


def test_p2_dash_punctuation_and_compact_or_explicit_ranges():
    text='# 2 Two\nSee §2 — 3 seats. Also §2–3 and §2 - §3.\n# 3 Three\n'
    refs=build_index(text.encode(),'docs/example.md',profile())['references']
    assert refs[0]['resolution']=='resolved' and not refs[0].get('range_end')
    assert [r['resolution'] for r in refs[1:]]==['range_unexpanded','range_unexpanded']


def test_p2_multiline_setext_and_unclosed_frontmatter_are_diagnosed():
    idx=build_index(b'Line one\nline two\n---\n','docs/example.md')
    assert any(d['code']=='unsupported_multiline_setext' for d in idx['diagnostics'])
    assert len(idx['sections'])==1
    idx=build_index(b'---\n# Title\nbody\n','docs/example.md')
    assert [s['heading'] for s in idx['sections']]==['','Title']
    assert any(d['code']=='unclosed_frontmatter' for d in idx['diagnostics'])


def test_p2_planned_metadata_and_event_skip_counts():
    row=dict(id='f',claim='c',location='a.md:1')
    rows,diag=load_findings([{'type':'metadata'},{'record_type':'event'},row])
    assert rows==[row] and len(diag['skipped'])==2


def test_p2_planned_heading_annotation_capture():
    text='# A (card 17, ruled yes)\n'
    idx=build_index(text.encode(),'docs/example.md',profile())
    assert sorted((c['key'],c['value']) for c in idx['candidates'])==[('card','17'),('ruled','yes)')]


def test_p2_planned_heading_status_identity_drift():
    old=build_index(b'# A **Canonical in direction**\n','docs/example.md')
    new=build_index(b'# A **Canonical**\n','docs/example.md',previous=old)
    assert old['sections'][1]['section_id'] in new['comparison']['removed']


def test_p2_planned_hook_import_performs_no_hook_action():
    script='''import importlib.util, sys
class NoRead:
    def read(self, *args):
        raise AssertionError('hook import read stdin')
    readline = read
sys.stdin = NoRead()
s = importlib.util.spec_from_file_location("hook", '''+repr(str(ROOT/'hooks/redact-melange-write.py'))+''')
m = importlib.util.module_from_spec(s)
s.loader.exec_module(m)
assert isinstance(m.MARKER, str)
'''
    proc=subprocess.run([sys.executable,'-c',script],input='not hook JSON',capture_output=True,text=True)
    assert proc.returncode==0 and proc.stdout==proc.stderr==''


def test_p2_markup_diagnostic_is_segment_local_with_positions():
    report,_=check('# A\nA `code` aside.\nThe **blue** door.\n','The blue door.')
    row=report['results'][0]
    assert row['status']=='mismatched'
    diagnostic=next(d for d in row['diagnostics'] if d['code']=='markup_drop_match')
    assert diagnostic['count']==len(diagnostic['spans'])==1
    assert diagnostic['spans'][0]['start_line']==3


def test_jsonl_uses_physical_newlines_even_inside_unicode_strings(tmp_path):
    text='# A\nword\u2028word\n'
    idx=build_index(text.encode(),'docs/example.md')
    doc,ip,fp=[tmp_path/name for name in ('doc.md','index.json','findings.jsonl')]
    doc.write_bytes(text.encode()); ip.write_text(json.dumps(idx))
    rows=[dict(id=str(i),claim='claim\u2028continued',location='example.md:2',
        quote=dict(section_id=idx['sections'][1]['section_id'],text='word\u2028word')) for i in range(2)]
    fp.write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows)+'\n')
    proc=subprocess.run([sys.executable,str(ROOT/'scripts/check_quotes.py'),'--document',str(doc),
        '--document-id','docs/example.md','--expected-sha256',digest(text.encode()),'--index',str(ip),
        '--findings',str(fp)],capture_output=True,text=True)
    assert proc.returncode==0
    assert len(json.loads(proc.stdout)['results'])==2
