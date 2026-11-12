"""R1: block boundaries inside a list retain that list's content context."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from markdown_section_index import build_index


@pytest.mark.parametrize('body',[
    '- item:\n  ```\n  x\n  ```\n    - nested see §1\n',
    '- item:\n  ***\n    - nested see §1\n',
    '- item\n    * * *\n\n    para see §1\n',
    '- item\n  Title\n  ---\n    - nested see §1\n',
    '- item\n    - nested\n      content\n    ```\n    x\n    ```\n    - next see §1\n',
])
def test_r1_list_container_survives_its_own_block_boundaries(body):
    profile=dict(schema_version=1,id='r1',version=1,rules=[
        dict(id='refs',scope='all',recognizer='section_reference')])
    idx=build_index(('# 1 A\n'+body).encode(),'docs/d.md',profile)
    assert [r['key'] for r in idx['references']]==['1']


def test_r1_second_list_fence_keeps_comment_and_references_inside_code():
    text='# 1 A\n- item:\n  ```\n  x\n  ```\n  ```html\n  <!-- not a comment\n  see §99\n  ```\n# 2 B\n'
    profile=dict(schema_version=1,id='r1',version=1,rules=[
        dict(id='refs',scope='all',recognizer='section_reference')])
    idx=build_index(text.encode(),'docs/d.md',profile)
    assert [s['heading'] for s in idx['sections']]==['','1 A','2 B']
    assert not idx['references']
