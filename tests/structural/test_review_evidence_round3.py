"""Focused regressions requested after the second independent review."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from _review_evidence import digest,markdown_regions,source_lines
from markdown_section_index import build_index
from check_quotes import check_document


def profile():
    return dict(schema_version=1,id='round-three',version=1,rules=[
        dict(id='refs',scope='all',recognizer='section_reference'),
        dict(id='notes',scope='heading',recognizer='heading_annotation',vocabulary=['card','ruled'])])


@pytest.mark.parametrize('indent',[2,4,5])
def test_n1_list_fences_do_not_extract_or_hide_later_headings(indent):
    pad=' '*indent
    text='# 1 A\n- Example:\n'+''.join(pad+s+'\n' for s in (
        '```html','<!-- never closes','see §1','**Term Fake:** in code','```'))+'# 2 B\n<!-- real -->\n# 3 C\n'
    idx=build_index(text.encode(),'docs/d.md',profile())
    assert [s['heading'] for s in idx['sections']]==['','1 A','2 B','3 C']
    assert not idx['references'] and not idx['definitions']


@pytest.mark.parametrize('prefix',['* * *\n','- item\n```\nexample\n```\n','- item\n    * * *\n'])
def test_n1_fences_and_thematic_break_reset_list_context(prefix):
    text=prefix+'\n    real code §88\n'
    idx=build_index(text.encode(),'docs/d.md',profile())
    assert not idx['references']


@pytest.mark.parametrize('doc,location',[
    ('docs/d.md','interverse/x/docs/d.md:2'),
    ('docs/design/game-design.md','design/game-design.md:2')])
def test_n2_prefix_variants_are_uncertain_and_evaluated(doc,location):
    data=b'# A\nactual\n'; idx=build_index(data,doc)
    row=dict(id='f',claim='c',location=location,quote=dict(section_id=idx['sections'][1]['section_id'],text='absent'))
    report,code=check_document(data,doc,digest(data),idx,[row])
    result=report['results'][0]
    assert code==0 and result['status']=='mismatched'
    assert 'location_uncertain' in {d['code'] for d in result['diagnostics']}


def test_n2_prefix_relation_does_not_silently_establish_identity():
    data=b'# A\nactual\n'; doc='docs/d.md'; idx=build_index(data,doc)
    row=dict(id='f',claim='c',location='prefix/docs/d.md:2',quote=dict(section_id=idx['sections'][1]['section_id'],text='actual'))
    report,_=check_document(data,doc,digest(data),idx,[row])
    result=report['results'][0]
    assert result['status']=='matched' and result['support']=='unverified'
    assert any(d['code']=='location_uncertain' for d in result['diagnostics'])
    row['location']='other/d.md:2'
    report,_=check_document(data,doc,digest(data),idx,[row])
    assert report['findings'][0]['status']=='out_of_scope'


def test_n3_html_block_closing_line_cannot_invent_heading():
    idx=build_index(b'<!--\nfoo\n-->## Fake\n# Real\n','docs/d.md')
    assert [s['heading'] for s in idx['sections']]==['','Real']


def test_n3_comment_edit_does_not_change_implicit_heading_identity():
    old=build_index(b'# A <!-- x --> B\n','docs/d.md')
    new=build_index(b'# A <!-- much longer comment --> B\n','docs/d.md')
    assert old['sections'][1]['section_id']==new['sections'][1]['section_id']
    assert old['sections'][1]['heading']==new['sections'][1]['heading']


def test_n3_multiline_inline_comment_hiding_heading_is_diagnosed():
    text='# A\nThe marker <!-- opens.\n# B\n<!-- closes -->\n# C\n'
    idx=build_index(text.encode(),'docs/d.md')
    diagnostic=next(d for d in idx['diagnostics'] if d['code']=='multiline_inline_comment')
    assert diagnostic['count']==1 and diagnostic['spans'][0]['start_line']==2


def test_n4_annotation_values_exclude_closing_parenthesis():
    idx=build_index(b'# A (card 17, ruled yes)\n','docs/d.md',profile())
    assert sorted((c['key'],c['value']) for c in idx['candidates'])==[('card','17'),('ruled','yes')]


def test_unclosed_comment_diagnostic_points_at_original_opener():
    text='# A\ntext <!-- never closes\n'
    idx=build_index(text.encode(),'docs/d.md')
    diagnostic=next(d for d in idx['diagnostics'] if d['code']=='unclosed_comment')
    assert diagnostic['spans']==[dict(start_line=2,start_column=6,end_line=2,end_column=10)]
