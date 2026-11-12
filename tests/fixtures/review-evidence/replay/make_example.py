"""Materialize independently authored synthetic data with current parser hashes."""
import argparse
import json
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[3]/'scripts'))
from _review_evidence import canonical_json
from markdown_section_index import build_index
from score_review_replay import evaluate_files,SNAPSHOT_KEYS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args(); output=Path(args.output); output.mkdir(parents=True,exist_ok=True)
    case=json.loads((HERE/'case.json').read_text())
    index=build_index((HERE/'document.md').read_bytes(),'docs/example.md')
    snap={key:index[key] for key in SNAPSHOT_KEYS}
    items=[]
    for row in case['items']:
        item={k:v for k,v in row.items() if k!='section'}
        item['sections']=[index['sections'][row['section']]['section_id']]; items.append(item)
    (output/'index.json').write_bytes(canonical_json(index))
    (output/'gold.json').write_bytes(canonical_json(dict(schema_version=1,snapshot=snap,index='index.json',items=items)))
    (output/'findings.jsonl').write_bytes(b''.join(canonical_json(row) for row in case['findings']))
    (output/'runs.json').write_bytes(canonical_json(dict(schema_version=1,runs=[dict(id='synthetic-run',snapshot=snap,
        findings='findings.jsonl',input_mode='snapshot',stage='post_adjudication',passes=['blind-a'])])))
    candidates,code=evaluate_files(output/'gold.json',output/'runs.json')
    if code:
        return code
    binding=dict(run_id='synthetic-run',ablation_id=None,inputs_sha256=candidates['runs'][0]['inputs_sha256'])
    judge=dict(id='synthetic-human',kind='human',family='human')
    records=[]
    for f,g in case['matches']:
        records.append(dict(binding,id=f'j-{len(records)}',type='match',finding_id=f,gold_id=g,
            verdict='same_issue',judge=judge,reason='Synthetic fixture declaration, not a real review.'))
    for f in case['extras']:
        records.append(dict(binding,id=f'j-{len(records)}',type='extra',finding_id=f,
            verdict='valid',judge=judge,reason='Synthetic fixture declaration, not a real review.'))
    coverage=[dict(binding,id='synthetic-coverage',type='semantic',complete=True,judge=judge,
        reason='Synthetic fixture covers the whole selected finding/gold universe.')]
    (output/'judgments.json').write_bytes(canonical_json(dict(schema_version=1,judgments=records,resolutions=[],coverage=coverage)))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
