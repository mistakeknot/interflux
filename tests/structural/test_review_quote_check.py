"""Synthetic contract tests; no review or document-derived fixtures."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))


def module():
    assert (ROOT / 'scripts/check_quotes.py').exists(), 'quote checker missing'
    import check_quotes
    return check_quotes


def index(text):
    from _review_evidence import digest, seal_index, parser_hash
    lines = text.splitlines(keepends=True)
    return seal_index(dict(schema_version=1, document_id='docs/example.md',
        document_sha256=digest(text.encode()), parser_version='markdown-sections-v1',
        parser_sha256=parser_hash(), syntax_profile=None,
        sections=[dict(section_id='a', line_range=dict(start=1, end=2), subtree_line_range=dict(start=1, end=4)),
                  dict(section_id='b', line_range=dict(start=3, end=len(lines)), subtree_line_range=dict(start=3, end=len(lines)))],
        diagnostics=[]))


def check(quote, text='# A\nThe “blue” door.\n# B\nOther words.\n', **fields):
    m = module()
    from _review_evidence import digest
    finding = dict(id='f', claim='A claim', location='docs/example.md:2', quote=quote, **fields)
    return m.check_document(text.encode(), 'docs/example.md', digest(text.encode()), index(text), [finding])


@pytest.mark.parametrize('quote,status,reason', [
    (None, 'missing', 'absent'),
    ({'section_id':'a','text':'The “blue” door.'}, 'matched','literal'),
    ({'section_id':'a','text':'The "blue"   door.'}, 'matched','normalized'),
    ({'section_id':'a','text':'Other words.'}, 'mismatched','not_present'),
    ({'section_id':'a','text':'The ... door.'}, 'unverifiable','elision_ambiguous'),
    ({'section_id':'unknown','text':'door'}, 'unverifiable','unknown_section'),
    ([], 'unverifiable','invalid_quote_container'),
    (42, 'unverifiable','invalid_quote_container'),
    ({'section_id':'a','text':42}, 'unverifiable','invalid_quote'),
])
def test_presence_contract(quote, status, reason):
    report, code = check(quote)
    row = report['results'][0]
    assert (row['status'], row['reason'], row['support']) == (status, reason, 'unverified')
    assert code == (1 if status == 'unverifiable' else 0)


def test_array_rollup_and_source_positions():
    report, code = check([{'section_id':'a','text':'door'}, {'section_id':'b','text':'absent'}, None])
    assert code == 1
    assert [r['quote_index'] for r in report['results']] == [0,1,2]
    assert report['findings'][0]['counts'] == dict(matched=1,mismatched=1,unverifiable=1)
    assert report['results'][0]['spans'][0] == dict(start_line=2,start_column=12,end_line=2,end_column=16)


def test_repetition_and_no_normalization_inside_code():
    report, _ = check({'section_id':'a','text':'blue'}, '# A\nblue blue\n# B\nother\n')
    assert report['results'][0]['occurrence_ambiguous']
    report, _ = check({'section_id':'a','text':'`a b`'}, '# A\n`a   b`\n# B\nother\n')
    assert report['results'][0]['status'] == 'mismatched'


def test_redaction_and_transform_precede_presence():
    spec = importlib.util.spec_from_file_location('redactor', ROOT/'hooks/redact-melange-write.py')
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    report, _ = check({'section_id':'a','text':hook.MARKER}, f'# A\n{hook.MARKER}\n# B\nother\n')
    assert report['results'][0]['reason'] == 'redacted'
    report, _ = check({'section_id':'a','text':'door','provenance':{'text_state':'transformed'}})
    assert report['results'][0]['reason'] == 'transformed'


def test_invalid_snapshot_has_no_evaluations():
    m = module()
    text = '# A\none\n# B\ntwo\n'
    idx = index(text)
    idx['document_sha256'] = '0'*64
    report, code = m.check_document(text.encode(), 'docs/example.md', '0'*64, idx, [])
    assert code == 2 and report['run_status'] == 'invalid_snapshot'
    assert not report['results']


def test_rows_duplicate_stamp_and_immutable_mutation():
    module()
    from _review_evidence import load_findings
    row = dict(id='f',claim='claim',location='docs/example.md:2',status='raw')
    assert len(load_findings([row,row], 'snapshot')[0]) == 1
    assert load_findings([row, dict(row,status='upheld')], 'ledger')[0][0]['status'] == 'upheld'
    with pytest.raises(ValueError):
        load_findings([row,dict(row,claim='different')], 'ledger')
    with pytest.raises(ValueError):
        load_findings([row,dict(row,status='upheld')], 'snapshot')
    with pytest.raises(ValueError):
        load_findings([{'status':'upheld','id':'f'}], 'ledger')


def test_other_document_is_out_of_scope():
    report, code = check({'section_id':'a','text':'door'}, document_id='other.md')
    assert report['findings'][0]['status'] == 'out_of_scope' and code == 0


def test_imported_rows_require_original_evidence():
    report, code = check({'section_id':'a','text':'door'}, source={'import':'synthetic'})
    assert code == 1 and report['results'][0]['reason']=='transformation_unknown'


@pytest.mark.parametrize('provenance',[None,42,{'text_state':'bogus'}])
def test_invalid_provenance_is_unverifiable(provenance):
    report, code = check({'section_id':'a','text':'door','provenance':provenance})
    assert code == 1 and report['results'][0]['reason']=='invalid_provenance'


def test_substring_of_redacted_source_is_unverifiable():
    m = module()
    text = f'# A\n{m.redaction_marker()}\n# B\nother\n'
    report,code = check({'section_id':'a','text':'SECRET'},text)
    assert code == 1 and report['results'][0]['reason']=='redacted'


def test_descendant_boundary_markup_and_location_diagnostics():
    report,_ = check({'section_id':'a','text':'Other words.'})
    assert 'present_in_descendant' in {d['code'] for d in report['results'][0]['diagnostics']}
    report,_ = check({'section_id':'a','text':'blue'},'# A\n**blue**\n# B\nother\n')
    assert report['results'][0]['status']=='matched'
    report,_ = check({'section_id':'a','text':'The blue door'},'# A\nThe **blue** door\n# B\nother\n')
    assert report['results'][0]['status']=='mismatched'
    assert 'markup_drop_match' in {d['code'] for d in report['results'][0]['diagnostics']}


def test_structural_index_range_failure():
    m = module()
    from _review_evidence import digest, seal_index
    text = '# A\none\n# B\ntwo\n'
    idx = index(text)
    idx['sections'][0]['line_range']['end']=999
    idx = seal_index(idx)
    report,code = m.check_document(text.encode(),'docs/example.md',digest(text.encode()),idx,[])
    assert code==2 and report['results']==[]


def test_duplicate_json_keys_rejected():
    module()
    from _review_evidence import read_json, document_id
    with pytest.raises(ValueError):
        read_json('{"a":1,"a":2}')
    for bad in ('/absolute','../escape','C:\\private',''):
        with pytest.raises(ValueError):
            document_id(bad)
