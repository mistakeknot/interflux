"""Exact priority matching for externally adjudicated review findings.

No lexical similarity or location heuristic creates semantic edges. Production
uses flow feasibility; exhaustive enumeration belongs only in synthetic tests.
"""
from __future__ import annotations

from collections import deque


class PriorityMatcher:
    def __init__(self,gold,findings,edges):
        self.gold=dict(gold)
        self.findings=set(findings)
        self.edges=set(edges)  # (finding ID, gold ID)
        if any(kind not in ('decision','plain_fix') for kind in self.gold.values()):
            raise ValueError('invalid_gold_kind')
        if any(f not in self.findings or g not in self.gold for f,g in self.edges):
            raise ValueError('dangling_edge')
        self.order=sorted(self.gold,key=lambda g:(self.gold[g]!='decision',g))
        self.bounds=tuple(sum(k==kind for k in self.gold.values()) for kind in ('decision','plain_fix'))

    def feasible(self,d,p,forced_edges=(),forbidden_edges=()):
        if type(d) is not int or type(p) is not int or d<0 or p<0:
            return None
        forced,forbidden=set(forced_edges),set(forbidden_edges)
        if not forced<=self.edges or forced&forbidden:
            return None
        used_f={f for f,_ in forced}; used_g={g for _,g in forced}
        if len(used_f)!=len(forced) or len(used_g)!=len(forced):
            return None
        quotas={'decision':d,'plain_fix':p}
        for _,g in forced:
            quotas[self.gold[g]]-=1
        if any(v<0 for v in quotas.values()):
            return None
        source,sink=('source',),('sink',)
        residual={}; adjacent={}
        def edge(a,b,capacity):
            residual[a,b]=capacity; residual[b,a]=0
            adjacent.setdefault(a,set()).add(b); adjacent.setdefault(b,set()).add(a)
        for f in sorted(self.findings-used_f):
            edge(source,('finding',f),1)
        remaining=[]
        for f,g in sorted(self.edges-forbidden):
            if f not in used_f and g not in used_g:
                edge(('finding',f),('gold',g),1); remaining.append((f,g))
        for g in self.order:
            if g not in used_g:
                edge(('gold',g),('kind',self.gold[g]),1)
        for kind in ('decision','plain_fix'):
            edge(('kind',kind),sink,quotas[kind])
        flow=0; target=sum(quotas.values())
        while flow<target:
            queue=deque([source]); previous={source:None}
            while queue and sink not in previous:
                a=queue.popleft()
                for b in sorted(adjacent.get(a,())):
                    if b not in previous and residual[a,b]>0:
                        previous[b]=a; queue.append(b)
            if sink not in previous:
                return None
            node=sink
            while previous[node] is not None:
                before=previous[node]
                residual[before,node]-=1; residual[node,before]+=1; node=before
            flow+=1
        result={g:f for f,g in forced}
        result.update({g:f for f,g in remaining if residual[('finding',f),('gold',g)]==0})
        return result

    def optimum(self):
        for d in range(min(self.bounds[0],len(self.findings)),-1,-1):
            for p in range(min(self.bounds[1],len(self.findings)-d),-1,-1):
                if self.feasible(d,p) is not None:
                    return d,p
        raise AssertionError('empty matching must be feasible')

    def canonical(self,d,p,forced_edges=(),forbidden_edges=()):
        forced,forbidden=set(forced_edges),set(forbidden_edges)
        if self.feasible(d,p,forced,forbidden) is None:
            return None
        for g in self.order:
            if any(g==chosen for _,chosen in forced):
                continue
            options=sorted(f for f,other in self.edges-forbidden if other==g)+[None]
            for f in options:
                test_forced=forced|{(f,g)} if f is not None else forced
                test_forbidden=forbidden if f is not None else forbidden|{e for e in self.edges if e[1]==g}
                if self.feasible(d,p,test_forced,test_forbidden) is not None:
                    forced,forbidden=test_forced,test_forbidden; break
            else:
                raise AssertionError('canonical assignment lost feasible objective')
        return self.feasible(d,p,forced,forbidden)

    def maximum_cardinality(self):
        """Independent, unweighted alternating-path BFS (no kind quotas)."""
        by_gold={}; by_finding={}
        for start in sorted(self.findings):
            queue=deque([start]); seen_f={start}; parent_g={}; end=None
            while queue and end is None:
                f=queue.popleft()
                for g in sorted(g for other,g in self.edges if other==f):
                    if g in parent_g:
                        continue
                    parent_g[g]=f
                    if g not in by_gold:
                        end=g; break
                    nxt=by_gold[g]
                    if nxt not in seen_f:
                        seen_f.add(nxt); queue.append(nxt)
            while end is not None:
                f=parent_g[end]; old=by_finding.get(f)
                by_gold[end]=f; by_finding[f]=end; end=old
        return len(by_gold)

    def rows(self,mapping):
        return [dict(gold_id=g,finding_id=mapping[g]) for g in self.order if g in mapping]

    def analyze(self):
        d,p=self.optimum(); k=self.maximum_cardinality(); chosen=self.canonical(d,p)
        cardinal_pairs=[(a,k-a) for a in range(self.bounds[0]+1)
            if 0<=k-a<=self.bounds[1] and self.feasible(a,k-a) is not None]
        membership=[]; priority=[]
        for f,g in sorted(self.edges,key=lambda e:(self.order.index(e[1]),e[0])):
            allowed=self.feasible(d,p,{(f,g)}) is not None
            membership.append(dict(gold_id=g,finding_id=f,in_some_priority_optimum=allowed,
                in_some_maximum_cardinality_matching=any(self.feasible(a,b,{(f,g)}) is not None for a,b in cardinal_pairs)))
            if allowed and chosen.get(g)!=f:
                witness=self.canonical(d,p,{(f,g)})
                priority.append(dict(forced_edge=dict(gold_id=g,finding_id=f),assignment=self.rows(witness),
                    changed_gold_assignments=[dict(gold_id=key,from_finding_id=chosen.get(key),to_finding_id=witness.get(key))
                        for key in self.order if chosen.get(key)!=witness.get(key)]))
        gold_ambiguity=[]
        for g in self.order:
            possible=sorted(row['finding_id'] for row in membership if row['gold_id']==g and row['in_some_priority_optimum'])
            unmatched=self.feasible(d,p,forbidden_edges={e for e in self.edges if e[1]==g}) is not None
            ambiguous=len(possible)+int(unmatched)>1
            gold_ambiguity.append(dict(gold_id=g,selected_finding_id=chosen.get(g),possible_finding_ids=possible,
                unmatched_possible=unmatched,assignment_ambiguous=ambiguous,occurrence_ambiguous=ambiguous))
        finding_ambiguity=[]
        for f in sorted(self.findings):
            possible=[row['gold_id'] for row in membership if row['finding_id']==f and row['in_some_priority_optimum']]
            unmatched=self.feasible(d,p,forbidden_edges={e for e in self.edges if e[0]==f}) is not None
            finding_ambiguity.append(dict(finding_id=f,possible_gold_ids=possible,unmatched_possible=unmatched,
                occurrence_ambiguous=len(possible)+int(unmatched)>1))
        recall=[]
        for a,b in cardinal_pairs:
            if (a,b)!=(d,p):
                recall.append(dict(decision_matches=a,plain_fix_matches=b,assignment=self.rows(self.canonical(a,b)),
                    changed_metrics=[metric for metric,x,y in (('decision_recall',a,d),('plain_fix_recall',b,p)) if x!=y]))
        return dict(matching=dict(objective='decision_then_plain_fix',decision_matches=d,plain_fix_matches=p,
                maximum_cardinality=k,assignment=self.rows(chosen)),
            ambiguity=dict(has_priority_optimal_alternative=any(g['occurrence_ambiguous'] for g in gold_ambiguity),
                edge_membership=membership,priority_alternatives=priority,recall_alternatives=recall,
                per_gold=gold_ambiguity,per_finding=finding_ambiguity))
