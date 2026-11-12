"""Section identity and declarative syntax tests on independently authored text."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))


def build(text, profile=None, previous=None):
    import markdown_section_index as m
    assert hasattr(m,'build_index'), 'index producer missing'
    return m.build_index(text.encode(),'docs/example.md',profile,previous)


def profile():
    return dict(schema_version=1,id='synthetic',version=1,rules=[
        dict(id='numbers',scope='heading',recognizer='numbered_heading',trailing_dot=True),
        dict(id='section',scope='all',recognizer='section_reference'),
        dict(id='relationship',scope='all',recognizer='relationship',
             vocabulary=['supersedes','superseded by','depends on'],case_sensitive=False),
        dict(id='term',scope='body',recognizer='bold_lead'),
        dict(id='status',scope='heading',recognizer='heading_status',vocabulary=['Canonical']),
        dict(id='annotations',scope='heading',recognizer='heading_annotation',vocabulary=['card','ruled'])])


def test_heading_ownership_excludes_code_comments_and_frontmatter():
    text = '---\nx: y\n---\npreamble\n# A\n```md\n# Fake\n```\n<!--\n# Hidden\n-->\n    # Code\nB\n===\nbody\n'
    idx = build(text)
    assert [s['heading'] for s in idx['sections']] == ['', 'A','B']
    ranges = [s['line_range'] for s in idx['sections']]
    assert [n for r in ranges for n in range(r['start'],r['end']+1)] == list(range(1,16))


def test_identity_drift_duplicate_ancestry_and_explicit_anchors():
    old = build('# A\nbody\n## Child\none\n# B {#fixed}\nend\n')
    new = build('intro\n# A\nchanged\n## Child\none\n# Renamed {#fixed}\nend\n',previous=old)
    assert [s['section_id'] for s in old['sections']] == [s['section_id'] for s in new['sections']]
    assert new['comparison']['content_changed']
    assert build('# Renamed\n')['sections'][1]['section_id'] != old['sections'][1]['section_id']
    dup = build('# A\n## Child\n# A\n## Child\n')
    assert all(s['identity_stability']=='snapshot_only' for s in dup['sections'][1:])
    with pytest.raises(ValueError,match='duplicate_anchor'):
        build('# A {#x}\n# B {#x}\n')


def test_number_terminator_and_relationship_lists_ranges_missing_targets():
    idx = build('# 1. Root **Canonical**\n**Depends on:** §2.1 and §2.2.\nSuperseded by: §2.1–2.2\nDepends on nothing yet.\n## 2.1. One\nx\n## 2.2 Two\nx\n',profile())
    assert [(s['number'],s['number_raw']) for s in idx['sections'][1:]] == [('1','1.'),('2.1','2.1.'),('2.2','2.2')]
    rels = [c for c in idx['candidates'] if c['kind']=='relationship_candidate']
    assert [len(c['targets']) for c in rels] == [2,1,0]
    assert rels[1]['relation']=='superseded_by'
    assert rels[1]['targets'][0]['resolution']=='range_unexpanded'
    assert rels[2]['resolution']=='no_target'
    assert all(r['resolution']=='resolved' for r in idx['references'] if r['kind']=='section' and not r.get('range_end'))
    generic = build('# 2.1. One\n')
    assert generic['sections'][1]['number'] is None


def test_definitions_references_candidates_and_ambiguity():
    idx = build('# Ruling alpha {#rule}\n**Term Gate:** A synthetic gate.\n[[ruling:alpha]] [[term:Gate]] [link](#rule) [web](https://example.invalid)\n[x][ref]\n[ref]: #rule\n# 2 One\n§2 §99\n**Portal:** A candidate.\n# 2 Two\n',profile())
    assert {d['kind'] for d in idx['definitions']} >= {'ruling','term','link'}
    assert len([r for r in idx['references'] if r['resolution']=='ambiguous']) == 1
    assert len([r for r in idx['references'] if r['resolution']=='unresolved']) == 1
    assert any(c['kind']=='term_candidate' for c in idx['candidates'])
    assert all('span' in c and 'label_span' in c for c in idx['candidates']+idx['definitions'])


@pytest.mark.parametrize('bad',[
    {'schema_version':2},
    dict(schema_version=1,id='x',version=1,rules=[dict(id='x',scope='all',recognizer='exec')]),
    dict(schema_version=1,id='x',version=1,rules=[dict(id='x',scope='all',recognizer='section_reference',code='bad')])])
def test_profiles_fail_closed(bad):
    with pytest.raises(ValueError):
        build('# A\n',bad)


def test_large_document_and_checker_cli(tmp_path):
    text = ''.join(f'# {n} Heading\nWords for section {n}.\n' for n in range(1,1001))
    idx = build(text,profile())
    assert len(idx['sections']) == 1001
    document,index,findings = [tmp_path/n for n in ('source.md','index.json','findings.jsonl')]
    document.write_text(text)
    index.write_text(json.dumps(idx))
    findings.write_text(json.dumps(dict(id='f',claim='Synthetic',location='docs/example.md:2',
        quote=dict(section_id=idx['sections'][1]['section_id'],text='Words for section 1.'))))
    proc = subprocess.run([sys.executable,str(ROOT/'scripts/check_quotes.py'),'--document',str(document),
        '--document-id','docs/example.md','--expected-sha256',idx['document_sha256'],'--index',str(index),
        '--findings',str(findings),'--json'],capture_output=True,text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)['results'][0]['status']=='matched'


def test_inline_code_in_heading_and_term_body_does_not_erase_structure():
    idx = build('# 1. Use `portal`\n**Gateway:** Use `portal` here.\n',profile())
    assert len(idx['sections'])==2
    assert len([c for c in idx['candidates'] if c['kind']=='term_candidate'])==1


def test_overlapping_status_vocabulary_uses_longest_literal_once():
    p = profile()
    p['rules'][4]['vocabulary']=['Canonical','Canonical in direction']
    idx = build('# 1 **Canonical in direction**\n',p)
    statuses = [c for c in idx['candidates'] if c['kind']=='status_candidate']
    assert len(statuses)==1 and statuses[0]['key']=='Canonical in direction'


def test_status_requires_emphasis_and_fixture_contract_hash_is_deterministic():
    p = profile()
    idx = build('# 1 Canonical\n',p)
    assert not [c for c in idx['candidates'] if c['kind']=='status_candidate']
    fixture = (ROOT/'tests/fixtures/review-evidence/sections.md').read_text()
    p = json.loads((ROOT/'tests/fixtures/review-evidence/syntax-profile.json').read_text())
    one,two = build(fixture,p),build(fixture,p)
    assert one==two
    p['version']=2
    assert build(fixture,p)['index_sha256'] != one['index_sha256']


def test_empty_document_no_owned_lines_and_number_spelling_distinction():
    empty = build('')
    assert empty['sections'][0]['line_range']==dict(start=1,end=0)
    idx = build('# 01 One\n§1 §01\n',profile())
    assert [r['resolution'] for r in idx['references']]==['unresolved','resolved']
