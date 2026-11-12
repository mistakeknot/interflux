"""R4-1: list-contained fences end when their container ends."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from markdown_section_index import build_index


def parse(text):
    profile=dict(schema_version=1,id='r4-1',version=1,rules=[
        dict(id='refs',scope='all',recognizer='section_reference')])
    return build_index(text.encode(),'docs/d.md',profile)


def test_r4_1_minimal_two_fence_trigger_commonmark_headings():
    text='# 1 A\n1. x:\n   ```md\n   ```py\n   y §99\n   **Term Fake:** code\n   ```\n   ```\n\n2. next\n\n```rust\nz §99\n**Term Fake:** code\n```\n\n## 2 B\n\n## 3 C\n'
    idx=parse(text)
    assert [s['heading'] for s in idx['sections']]==['','1 A','2 B','3 C']
    assert not idx['references'] and not idx['definitions']


def test_r4_1_older_unclosed_first_list_fence():
    idx=parse('# 1 A\n- item\n  ```\n  code §99\n  **Term Fake:** code\n- next\n# 2 B\n')
    assert [s['heading'] for s in idx['sections']]==['','1 A','2 B']
    assert not idx['references'] and not idx['definitions']


@pytest.mark.parametrize('opening,closing',[(0,0),(0,2),(2,2),(2,0)])
def test_r4_1_list_and_column_zero_fence_boundaries(opening,closing):
    # On container exit a column-zero delimiter opens a NEW top-level fence.
    # It does not close the old item fence; the following delimiter closes it.
    tail='outside §99\n**Term Fake:** code\n```\n' if opening==2 and closing==0 else ''
    text='# 1 A\n- item\n'+' '*opening+'```md\n  inside §99\n  **Term Fake:** code\n'+' '*closing+'```\n'+tail+'# 2 B\n'
    idx=parse(text)
    assert [s['heading'] for s in idx['sections']]==['','1 A','2 B']
    assert not idx['references'] and not idx['definitions']


def test_r4_1_blank_lines_do_not_end_list_fence():
    idx=parse('# 1 A\n- item\n  ```\n\n  §99\n  **Term Fake:** code\n  ```\n# 2 B\n')
    assert [s['heading'] for s in idx['sections']]==['','1 A','2 B']
    assert not idx['references'] and not idx['definitions']
