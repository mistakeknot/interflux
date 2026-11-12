"""Synthetic replay contracts and a test-only exhaustive matching oracle."""
import itertools
import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))


def matcher(gold,findings,edges):
    assert (ROOT/'scripts/_review_replay.py').exists(),'replay matcher missing'
    from _review_replay import PriorityMatcher
    return PriorityMatcher(gold,findings,edges)


def assignment(rows):
    return {r['gold_id']:r['finding_id'] for r in rows}


def oracle(gold,findings,edges):
    order=sorted(gold,key=lambda g:(gold[g]!='decision',g))
    results=[]
    def walk(i,used,chosen):
        if i==len(order):
            results.append(dict(chosen)); return
        g=order[i]
        for f in sorted(findings):
            if f not in used and (f,g) in edges:
                walk(i+1,used|{f},dict(chosen,**{g:f}))
        walk(i+1,used,chosen)
    walk(0,set(),{})
    def counts(a):
        return sum(gold[g]=='decision' for g in a),sum(gold[g]=='plain_fix' for g in a)
    optimum=max(map(counts,results))
    best=[a for a in results if counts(a)==optimum]
    key=lambda a:tuple((0,a[g]) if g in a else (1,'') for g in order)
    return results,optimum,min(best,key=key),counts


def test_decision_priority_and_recall_changing_alternative():
    m=matcher({'a-fix':'plain_fix','z-decision':'decision'},['f'],[('f','a-fix'),('f','z-decision')])
    result=m.analyze()
    assert assignment(result['matching']['assignment'])=={'z-decision':'f'}
    assert result['matching']['maximum_cardinality']==1
    assert result['ambiguity']['recall_alternatives'][0]['decision_matches']==0
    assert result['ambiguity']['recall_alternatives'][0]['plain_fix_matches']==1


def test_augmenting_reassignment_preserves_decision_and_adds_fix():
    m=matcher({'d':'decision','p':'plain_fix'},['a','b'],[('a','d'),('b','d'),('a','p')])
    result=m.analyze()
    assert assignment(result['matching']['assignment'])=={'d':'b','p':'a'}
    assert (result['matching']['decision_matches'],result['matching']['plain_fix_matches'])==(1,1)
    assert m.feasible(1,1,{('a','d')},set()) is None
    assert m.feasible(-1,0,set(),set()) is None
    assert m.feasible(1,0,{('not-found','d')},set()) is None


def test_per_gold_unmatched_possibility_and_occurrence_ambiguity():
    m=matcher({'a':'decision','b':'decision'},['f'],[('f','a'),('f','b')])
    result=m.analyze()
    assert all(g['unmatched_possible'] and g['occurrence_ambiguous'] for g in result['ambiguity']['per_gold'])
    assert len(result['ambiguity']['priority_alternatives'])==1
    witness=result['ambiguity']['priority_alternatives'][0]
    assert assignment(witness['assignment'])=={'b':'f'}
    assert len(witness['changed_gold_assignments'])==2
    # Forbidding ALL incident edges, not testing just one edge, proves unmatched.
    assert m.feasible(1,0,set(),{('f','a')}) is not None


def test_permutation_and_duplicate_edges_do_not_change_matching():
    gold={'d':'decision','p':'plain_fix'}; findings=['a','b']; edges=list(itertools.product(findings,gold))
    first=matcher(gold,findings,edges).analyze()
    second=matcher(dict(reversed(list(gold.items()))),list(reversed(findings)),list(reversed(edges))+edges).analyze()
    assert first==second
    assert assignment(first['matching']['assignment'])=={'d':'a','p':'b'}


@pytest.mark.parametrize('kinds,findings',[
    ({'a':'decision','b':'decision','c':'plain_fix'},['x','y']),
    ({'a':'decision','b':'plain_fix','c':'plain_fix'},['x','y']),
    ({'a':'decision','b':'plain_fix'},['x','y','z'])])
def test_exhaustive_small_graph_oracle(kinds,findings):
    potential=list(itertools.product(findings,kinds))
    for mask in range(1<<len(potential)):
        edges={edge for i,edge in enumerate(potential) if mask&(1<<i)}
        all_assignments,optimum,canonical,counts=oracle(kinds,findings,edges)
        result=matcher(kinds,findings,edges).analyze()
        matching=result['matching']; ambiguity=result['ambiguity']
        assert (matching['decision_matches'],matching['plain_fix_matches'])==optimum
        assert assignment(matching['assignment'])==canonical
        k=max(map(len,all_assignments))
        assert matching['maximum_cardinality']==k==sum(optimum)
        best=[a for a in all_assignments if counts(a)==optimum]
        for row in ambiguity['edge_membership']:
            f,g=row['finding_id'],row['gold_id']
            assert row['in_some_priority_optimum']==any(a.get(g)==f for a in best)
            assert row['in_some_maximum_cardinality_matching']==any(len(a)==k and a.get(g)==f for a in all_assignments)
        for row in ambiguity['per_gold']:
            options={a.get(row['gold_id']) for a in best}
            assert row['unmatched_possible']==(None in options)
            assert row['occurrence_ambiguous']==(len(options)>1)
        expected={counts(a) for a in all_assignments if len(a)==k}-{optimum}
        assert {(a['decision_matches'],a['plain_fix_matches']) for a in ambiguity['recall_alternatives']}==expected
        for alt in ambiguity['priority_alternatives']:
            a=assignment(alt['assignment'])
            assert a in best and a[alt['forced_edge']['gold_id']]==alt['forced_edge']['finding_id']
