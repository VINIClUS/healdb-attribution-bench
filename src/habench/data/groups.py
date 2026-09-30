"""Document groups (protocol §4.2): connected components over identical, near-duplicate and translated texts.

Relations between medications (union-find):
  (a) identical normalized Portuguese indication text ("pt_exact");
  (b) near-duplicate Portuguese text: word 5-shingle Jaccard >= 0.90 on the normalized text ("pt_near");
  (c) identical stripped English translation ("en_exact").
The threshold is fixed a priori and is never tuned. The near-duplicate join is exact (prefix and size
filtering over an inverted index), not an approximation. "pt_near" in a medication's link means a near
pair with a *different* normalized text (identical texts are already "pt_exact").

No leaflet is shared across medications (hd_medication_drug_leaflet is 1:1), so leaflet sharing adds no
relation and that table is not loaded.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

SHINGLE = 5
JACCARD_NUM, JACCARD_DEN = 9, 10  # threshold 0.90 as an exact fraction
_WS = re.compile(r"\s+")


def normalize_pt(s: str) -> str:
    s = unicodedata.normalize("NFC", s).strip()
    return _WS.sub(" ", s).casefold()


def shingles(text: str) -> frozenset[tuple[str, ...]]:
    """Word 5-shingles of a normalized text; fewer than 5 words give the single shingle of all words."""
    words = text.split()
    if len(words) < SHINGLE:
        return frozenset([tuple(words)])
    return frozenset(tuple(words[i : i + SHINGLE]) for i in range(len(words) - SHINGLE + 1))


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "surrogateescape")).hexdigest()


def group_id(meds: list[int] | tuple[int, ...]) -> str:
    return "g" + hashlib.sha256(",".join(str(m) for m in sorted(meds)).encode()).hexdigest()[:12]


class UnionFind:
    def __init__(self, items) -> None:
        self.parent = {i: i for i in items}

    def find(self, x):
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def near_pairs(sets: list[frozenset]) -> list[tuple[int, int]]:
    """All index pairs (i < j) with Jaccard(sets[i], sets[j]) >= 0.90, exactly (prefix + size filtering)."""
    freq: dict = defaultdict(int)
    for s in sets:
        for t in s:
            freq[t] += 1
    order = {t: k for k, t in enumerate(sorted(freq, key=lambda t: (freq[t], t)))}  # rare tokens first
    recs = [sorted(order[t] for t in s) for s in sets]
    by_size = sorted(range(len(sets)), key=lambda i: (len(recs[i]), i))
    index: dict[int, list[int]] = defaultdict(list)
    out = []
    for x in by_size:
        rx = recs[x]
        n = len(rx)
        if n == 0:
            continue
        need = -(-JACCARD_NUM * n // JACCARD_DEN)  # ceil(0.9 n)
        prefix = rx[: n - need + 1]
        cands: set[int] = set()
        for t in prefix:
            cands.update(index[t])
        sx = sets[x]
        for y in cands:
            ny = len(recs[y])
            if ny * JACCARD_DEN < JACCARD_NUM * n:  # size filter (y is not larger than x)
                continue
            inter = len(sx & sets[y])
            union = n + ny - inter
            if JACCARD_DEN * inter >= JACCARD_NUM * union:
                out.append((min(x, y), max(x, y)))
        for t in prefix:
            index[t].append(x)
    return sorted(out)


@dataclass(frozen=True, slots=True)
class Group:
    group_id: str
    meds: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MedGroup:
    group_id: str
    medication: int
    pt_sha256: str
    en_sha256: str
    link: str


def build_groups(texts: Mapping[int, tuple[str, str]]) -> tuple[list[Group], list[MedGroup]]:
    """Groups and per-medication records from {medication: (PT ds_indication, EN ds_indication_eng)}."""
    meds = sorted(texts)
    uf = UnionFind(meds)
    pt_norm = {m: normalize_pt(texts[m][0]) for m in meds}
    en_norm = {m: texts[m][1].strip() for m in meds}
    has_exact: dict[str, set[int]] = {"pt_exact": set(), "en_exact": set()}
    for name, key in (("pt_exact", pt_norm), ("en_exact", en_norm)):
        first: dict[str, int] = {}
        for m in meds:
            k = key[m]
            if k in first:
                uf.union(first[k], m)
                has_exact[name].update((first[k], m))
            else:
                first[k] = m
    # near-duplicates between distinct normalized texts
    holders: dict[str, list[int]] = defaultdict(list)
    for m in meds:
        holders[pt_norm[m]].append(m)
    uniq = sorted(holders)
    near: set[int] = set()
    for i, j in near_pairs([shingles(u) for u in uniq]):
        a, b = holders[uniq[i]], holders[uniq[j]]
        near.update(a)
        near.update(b)
        for m in (*a, *b):
            uf.union(a[0], m)
    comps: dict[int, list[int]] = defaultdict(list)
    for m in meds:
        comps[uf.find(m)].append(m)
    groups = sorted((Group(group_id(v), tuple(v)) for v in comps.values()), key=lambda g: g.group_id)
    gid = {m: g.group_id for g in groups for m in g.meds}
    size = {g.group_id: len(g.meds) for g in groups}
    records = []
    for m in meds:
        links = sorted(
            n for n, s in (("en_exact", has_exact["en_exact"]), ("pt_exact", has_exact["pt_exact"]), ("pt_near", near))
            if m in s
        )
        if size[gid[m]] == 1:
            links = []
        records.append(MedGroup(gid[m], m, _sha(texts[m][0]), _sha(texts[m][1]), ";".join(links) or "singleton"))
    return groups, records


def summarize(groups: list[Group], n_meds: int) -> dict:
    sizes: dict[int, int] = defaultdict(int)
    for g in groups:
        sizes[len(g.meds)] += 1
    largest = max(groups, key=lambda g: (len(g.meds), g.group_id))
    return {
        "groups": len(groups),
        "size_distribution": dict(sorted(sizes.items())),
        "largest_size": len(largest.meds),
        "largest_group": largest.group_id,
        "over_1pct": [(g.group_id, len(g.meds)) for g in groups if len(g.meds) > 0.01 * n_meds],
    }


def load_texts(snap: str = "v1") -> dict[int, tuple[str, str]]:
    """Universe texts: medications with a response row, from the translate table."""
    from habench.data.store import load_table

    universe = {int(i) for i in load_table(snap, "hd_int_med_disease_api_response", ["id_medication"]).column("id_medication").to_pylist()}
    tab = load_table(snap, "hd_translate_eng_leaflet_section", ["id_medication", "ds_indication", "ds_indication_eng"])
    out = {}
    for i, pt, en in zip(*(tab.column(c).to_pylist() for c in tab.schema.names)):
        if int(i) in universe:
            out[int(i)] = (pt or "", en or "")
    return out


def missing_translations(snap: str = "v1") -> list[int]:
    from habench.data.store import load_table

    universe = {int(i) for i in load_table(snap, "hd_int_med_disease_api_response", ["id_medication"]).column("id_medication").to_pylist()}
    return sorted(universe - set(load_texts(snap)))
