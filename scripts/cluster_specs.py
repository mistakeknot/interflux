#!/usr/bin/env python3
"""cluster_specs.py — partition agent specs into max-distance clusters for teams synthesis.

Input: list of spec JSON paths or a list of pre-loaded dicts. Each spec must contain at
least `source_domain`, `focus`, and `expected_isomorphisms` (strings). Optional but
preferred: `name`, `distance_rationale`.

Distance: lightweight character-trigram cosine over the concatenation of
`source_domain + " " + focus + " " + expected_isomorphisms`. We deliberately avoid
sentence-transformer embeddings: ~12 specs is small enough that BoW/trigram cosine
gives sufficient cluster-separability signal without the model load cost.

Algorithm: farthest-point sampling for K seeds (default 3), then assign remaining specs
to the closest seed. Audit pairwise centroid distances and degrade gracefully:

* `divergent_clusters_too_close`: if min pairwise centroid distance < threshold (default
  0.30), return that status and let the caller fall back to subagent path.
* `degraded_to_2_clusters`: if any cluster has < 3 specs after a rebalance pass, return
  K=2 clusters (downstream spawns 4 teammates instead of 5).
* `ok`: clusters pass both audits.

Always logs pairwise centroid distances and cluster sizes to stderr regardless of pass
or fail (P2 finding from plan review — observable from first smoke run).

Module API:
    cluster_specs(specs, k=3, threshold=0.30, seed=None) -> dict

CLI:
    python3 cluster_specs.py --specs-glob 'path/to/*.json' [--k 3] [--threshold 0.30] \
        [--seed 42]

Returns (or prints) JSON of:
    {
        "status": "ok" | "divergent_clusters_too_close" | "degraded_to_2_clusters",
        "reason": "...",  # human-readable, only when status != "ok"
        "k": int,
        "clusters": [
            {"index": 0, "specs": [<spec dict>, ...], "centroid_signature": "..."},
            ...
        ],
        "pairwise_centroid_distances": {"0-1": float, "0-2": float, "1-2": float},
        "sizes": [int, ...]
    }
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import random
import sys
from collections import Counter
from typing import Any


def _spec_text(spec: dict) -> str:
    """Concatenate the fields used for distance computation. Empty/missing fields tolerated."""
    parts = []
    for key in ("source_domain", "focus", "expected_isomorphisms"):
        val = spec.get(key) or ""
        if isinstance(val, list):
            val = " ".join(str(x) for x in val)
        parts.append(str(val).lower())
    return " ".join(parts)


def _trigrams(text: str) -> Counter[str]:
    """Character-trigram frequency vector over alphanumerics + spaces."""
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) < 3:
        # tiny inputs — fall back to single-char counts so cosine is still defined
        return Counter(cleaned)
    return Counter(cleaned[i : i + 3] for i in range(len(cleaned) - 2))


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    """Cosine similarity in [0, 1]. Returns 0 if either is empty."""
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[k] * b[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _distance(a: Counter[str], b: Counter[str]) -> float:
    """Distance = 1 - cosine, in [0, 1]."""
    return 1.0 - _cosine(a, b)


def _farthest_point_seeds(vectors: list[Counter[str]], k: int, rng: random.Random) -> list[int]:
    """Pick K seed indices via farthest-point sampling.

    Pick the first seed at random; each subsequent seed is the index whose minimum
    distance to all already-chosen seeds is maximized. Stable for our small N.
    """
    if k <= 0 or k > len(vectors):
        raise ValueError(f"k={k} out of range for {len(vectors)} vectors")

    seeds = [rng.randrange(len(vectors))]
    while len(seeds) < k:
        best_idx, best_min_dist = -1, -1.0
        for i in range(len(vectors)):
            if i in seeds:
                continue
            min_to_seeds = min(_distance(vectors[i], vectors[s]) for s in seeds)
            if min_to_seeds > best_min_dist:
                best_min_dist, best_idx = min_to_seeds, i
        if best_idx == -1:
            break
        seeds.append(best_idx)
    return seeds


def _assign(vectors: list[Counter[str]], seeds: list[int]) -> list[int]:
    """Return a list of seed-index assignments for each input vector (index into seeds)."""
    assignments = []
    for i, v in enumerate(vectors):
        if i in seeds:
            assignments.append(seeds.index(i))
            continue
        dists = [_distance(v, vectors[s]) for s in seeds]
        assignments.append(dists.index(min(dists)))
    return assignments


def _centroid_signature(cluster_vectors: list[Counter[str]]) -> Counter[str]:
    """Sum of trigram counts as a centroid surrogate (cheaper than mean; cosine is scale-invariant)."""
    centroid: Counter[str] = Counter()
    for v in cluster_vectors:
        centroid.update(v)
    return centroid


def _pairwise_centroid_distances(centroids: list[Counter[str]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for i in range(len(centroids)):
        for j in range(i + 1, len(centroids)):
            out[f"{i}-{j}"] = round(_distance(centroids[i], centroids[j]), 4)
    return out


def _rebalance(
    assignments: list[int],
    vectors: list[Counter[str]],
    k: int,
    min_size: int = 3,
) -> tuple[list[int], bool]:
    """One-pass rebalance: move outliers from the largest cluster into the smallest if any
    cluster has fewer than min_size specs. Returns (new_assignments, any_change_made).
    """
    sizes = [assignments.count(i) for i in range(k)]
    if all(s >= min_size for s in sizes):
        return assignments, False

    smallest = sizes.index(min(sizes))
    largest = sizes.index(max(sizes))
    if smallest == largest:
        return assignments, False

    # Compute each largest-cluster member's distance to its OWN centroid; the highest
    # is the outlier most worth moving.
    largest_members = [i for i, a in enumerate(assignments) if a == largest]
    largest_centroid = _centroid_signature([vectors[i] for i in largest_members])

    needed = min_size - sizes[smallest]
    distances = sorted(
        ((i, _distance(vectors[i], largest_centroid)) for i in largest_members),
        key=lambda x: -x[1],
    )

    new_assignments = list(assignments)
    moved = 0
    for i, _ in distances:
        if moved >= needed:
            break
        # Don't shrink the largest cluster below min_size.
        if sizes[largest] - 1 < min_size:
            break
        new_assignments[i] = smallest
        sizes[largest] -= 1
        sizes[smallest] += 1
        moved += 1

    return new_assignments, moved > 0


def cluster_specs(
    specs: list[dict],
    k: int = 3,
    threshold: float = 0.30,
    seed: int | None = None,
    min_size: int = 3,
) -> dict[str, Any]:
    """Cluster specs by max-distance partitioning. See module docstring for full semantics."""
    if not specs:
        return {
            "status": "empty",
            "reason": "no specs supplied",
            "k": 0,
            "clusters": [],
            "pairwise_centroid_distances": {},
            "sizes": [],
        }

    if len(specs) < k:
        # Cannot form K clusters; degrade to len(specs) clusters of size 1 — caller decides
        # whether that's usable. This is *different* from "degraded_to_2_clusters" because
        # we never even tried K; we just don't have material.
        return {
            "status": "insufficient_specs",
            "reason": f"have {len(specs)} specs, need >= {k}",
            "k": len(specs),
            "clusters": [{"index": i, "specs": [specs[i]]} for i in range(len(specs))],
            "pairwise_centroid_distances": {},
            "sizes": [1] * len(specs),
        }

    rng = random.Random(seed)
    vectors = [_trigrams(_spec_text(s)) for s in specs]

    seeds = _farthest_point_seeds(vectors, k, rng)
    assignments = _assign(vectors, seeds)
    assignments, _ = _rebalance(assignments, vectors, k, min_size=min_size)

    # If rebalance failed to bring all clusters to >= min_size, degrade K by 1 and retry.
    sizes = [assignments.count(i) for i in range(k)]
    degraded = False
    if any(s < min_size for s in sizes) and k > 2:
        degraded = True
        seeds = _farthest_point_seeds(vectors, k - 1, rng)
        assignments = _assign(vectors, seeds)
        assignments, _ = _rebalance(assignments, vectors, k - 1, min_size=min_size)
        k = k - 1
        sizes = [assignments.count(i) for i in range(k)]

    # Build clusters
    clusters: list[dict[str, Any]] = []
    centroids: list[Counter[str]] = []
    for ci in range(k):
        cluster_specs_list = [specs[i] for i, a in enumerate(assignments) if a == ci]
        cluster_vectors = [vectors[i] for i, a in enumerate(assignments) if a == ci]
        centroid = _centroid_signature(cluster_vectors)
        centroids.append(centroid)
        # Centroid signature for caller: top 5 trigrams (compact debug aid)
        sig = " ".join(f"{tg}({n})" for tg, n in centroid.most_common(5))
        clusters.append({"index": ci, "specs": cluster_specs_list, "centroid_signature": sig})

    pairwise = _pairwise_centroid_distances(centroids)

    # Always log to stderr (P2 plan review finding)
    print(
        f"cluster_specs: k={k} sizes={sizes} pairwise_centroid_distances={pairwise} "
        f"threshold={threshold} degraded={degraded}",
        file=sys.stderr,
    )

    if pairwise and min(pairwise.values()) < threshold:
        return {
            "status": "divergent_clusters_too_close",
            "reason": (
                f"min pairwise centroid distance {min(pairwise.values()):.4f} < threshold "
                f"{threshold}; specs are not differentiated enough for cross-cluster debate"
            ),
            "k": k,
            "clusters": clusters,
            "pairwise_centroid_distances": pairwise,
            "sizes": sizes,
        }

    if degraded:
        return {
            "status": "degraded_to_2_clusters",
            "reason": "could not maintain min cluster size at k=3; downstream spawns one fewer debater",
            "k": k,
            "clusters": clusters,
            "pairwise_centroid_distances": pairwise,
            "sizes": sizes,
        }

    return {
        "status": "ok",
        "k": k,
        "clusters": clusters,
        "pairwise_centroid_distances": pairwise,
        "sizes": sizes,
    }


def _load_specs_from_glob(pattern: str) -> list[dict]:
    paths = sorted(glob.glob(pattern))
    if not paths:
        raise SystemExit(f"cluster_specs: no files match {pattern}")
    specs: list[dict] = []
    for p in paths:
        with open(p) as f:
            data = json.load(f)
        if isinstance(data, list):
            specs.extend(data)
        elif isinstance(data, dict):
            specs.append(data)
        else:
            raise SystemExit(f"cluster_specs: unexpected JSON shape in {p}: {type(data).__name__}")
    return specs


def main() -> int:
    parser = argparse.ArgumentParser(description="Partition agent specs into max-distance clusters.")
    parser.add_argument("--specs-glob", required=True, help="Glob pattern for spec JSON files")
    parser.add_argument("--k", type=int, default=3, help="Number of clusters (default 3)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.30,
        help="Minimum acceptable pairwise centroid distance (default 0.30)",
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument(
        "--min-size",
        type=int,
        default=3,
        help="Minimum cluster size before degrading K (default 3)",
    )
    args = parser.parse_args()

    specs = _load_specs_from_glob(args.specs_glob)
    result = cluster_specs(specs, k=args.k, threshold=args.threshold, seed=args.seed, min_size=args.min_size)

    # Strip cluster.specs from CLI JSON output to keep it readable; full data via library API.
    cli_view = dict(result)
    cli_view["clusters"] = [
        {"index": c["index"], "size": len(c["specs"]), "centroid_signature": c.get("centroid_signature", "")}
        for c in result["clusters"]
    ]
    print(json.dumps(cli_view, indent=2))
    return 0 if result["status"] in ("ok", "degraded_to_2_clusters") else 1


if __name__ == "__main__":
    raise SystemExit(main())
