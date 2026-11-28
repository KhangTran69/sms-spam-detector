"""Local, aggregate-only overlap audit for approved public and synthetic SMS corpora."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.dataset_schema import (
    DEFAULT_HOLDOUT,
    DEFAULT_SUPPLEMENTS,
    _normalized_message_key,
    make_group_key,
)

PUBLIC_IDS = {
    "uci": "uci-sms-spam-collection-228",
    "ph_inbox": "ph-spam-marketing-sms-w-timestamps",
    "tagalog": "tagalog-sms",
}
SYNTHETIC_ROLES = {"synthetic_training", "synthetic_holdout"}
MAX_ROWS = 20_000
MAX_BYTES = 50 * 1024 * 1024
MAX_MESSAGE_LENGTH = 10_000
COSINE_THRESHOLD = 0.90
SEQUENCE_THRESHOLD = 0.90
BLOCK_SIZE = 64


@dataclass(frozen=True)
class Corpus:
    role: str
    messages: tuple[str, ...]
    labels: tuple[str, ...]
    source_hashes: tuple[str, ...]


def load_corpus(role: str, paths: list[Path]) -> Corpus:
    """Read a bounded snapshot; do not deduplicate before measuring overlap."""
    if role not in PUBLIC_IDS and role not in SYNTHETIC_ROLES:
        raise ValueError("Unsupported corpus role.")
    if not paths or (role in PUBLIC_IDS and len(paths) != 1):
        raise ValueError("Unexpected number of files for corpus role.")
    messages: list[str] = []
    labels: list[str] = []
    hashes: list[str] = []
    total_bytes = 0
    for path in paths:
        with path.open("rb") as handle:
            content = handle.read(MAX_BYTES - total_bytes + 1)
        total_bytes += len(content)
        if total_bytes > MAX_BYTES:
            raise ValueError("Corpus exceeds the local audit byte budget.")
        hashes.append(hashlib.sha256(content).hexdigest())
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), strict=True)
        fields = reader.fieldnames or []
        required = {"message", "label", "data_kind"}
        if role in PUBLIC_IDS:
            required.add("dataset_id")
        if len(fields) != len(set(fields)) or not required.issubset(fields):
            raise ValueError("Expected normalized public or synthetic CSV columns.")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed CSV row.")
            expected_kind = "public" if role in PUBLIC_IDS else "synthetic"
            if row["data_kind"] != expected_kind or (role in PUBLIC_IDS and row["dataset_id"] != PUBLIC_IDS[role]):
                raise ValueError("Corpus provenance does not match its approved role.")
            message, label = row["message"], row["label"]
            if not message.strip() or len(message) > MAX_MESSAGE_LENGTH or label not in {"ham", "spam"}:
                raise ValueError("Invalid message length or label in corpus.")
            messages.append(message)
            labels.append(label)
            if len(messages) > MAX_ROWS:
                raise ValueError("Corpus exceeds the local audit row budget.")
    if not messages:
        raise ValueError("Corpus is empty.")
    return Corpus(role, tuple(messages), tuple(labels), tuple(hashes))


def _overlap(left: list[str], right: list[str]) -> dict[str, int]:
    a, b = Counter(left), Counter(right)
    shared = a.keys() & b.keys()
    return {
        "distinct_keys": len(shared),
        "left_rows": sum(a[key] for key in shared),
        "right_rows": sum(b[key] for key in shared),
        "row_pairs": sum(a[key] * b[key] for key in shared),
    }


def compare_corpora(left: Corpus, right: Corpus) -> dict[str, Any]:
    """Compare one pair without reporting individual texts, keys, or row IDs."""
    a = [_normalized_message_key(message) for message in left.messages]
    b = [_normalized_message_key(message) for message in right.messages]
    counts_a = Counter(zip(a, left.labels))
    counts_b = Counter(zip(b, right.labels))
    conflicts = sum(
        count * counts_b.get((key, "spam" if label == "ham" else "ham"), 0) for (key, label), count in counts_a.items()
    )
    # Fit on this pair only. Blocks bound the dense similarity allocation.
    vectors = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), dtype=float).fit_transform(a + b)
    right_vectors = vectors[len(a) :]
    candidates = 0
    near_conflicts = 0
    for start in range(0, len(a), BLOCK_SIZE):
        scores = cosine_similarity(vectors[start : min(start + BLOCK_SIZE, len(a))], right_vectors)
        for offset, j in zip(*(scores >= COSINE_THRESHOLD).nonzero()):
            i = start + int(offset)
            j = int(j)
            if a[i] == b[j]:
                continue
            if SequenceMatcher(None, a[i], b[j], autojunk=False).ratio() >= SEQUENCE_THRESHOLD:
                candidates += 1
                near_conflicts += int(left.labels[i] != right.labels[j])
    return {
        "left": left.role,
        "right": right.role,
        "exact": _overlap(list(left.messages), list(right.messages)),
        "normalized": _overlap(a, b),
        "category_independent_template": _overlap(
            [make_group_key(message) for message in left.messages],
            [make_group_key(message) for message in right.messages],
        ),
        "normalized_conflicting_label_pairs": conflicts,
        "near_duplicate_pairs_excluding_normalized": candidates,
        "near_duplicate_conflicting_label_pairs": near_conflicts,
    }


def audit(corpora: list[Corpus]) -> dict[str, Any]:
    if len(corpora) < 2 or len({corpus.role for corpus in corpora}) != len(corpora):
        raise ValueError("Provide at least two distinct corpus roles.")
    if sum(len(corpus.messages) for corpus in corpora) > MAX_ROWS:
        raise ValueError("Combined corpora exceed the local audit row budget.")
    return {
        "schema_version": 1,
        "purpose": "diagnostic_overlap_only",
        "method": {
            "normalization": "NFKC, casefold, whitespace collapse",
            "template": "project category-independent template key",
            "near_duplicate": "pair-local char_wb TF-IDF 3-5 grams and SequenceMatcher",
            "cosine_threshold": COSINE_THRESHOLD,
            "sequence_threshold": SEQUENCE_THRESHOLD,
        },
        "corpora": [
            {
                "role": corpus.role,
                "source_sha256": list(corpus.source_hashes),
                "rows": len(corpus.messages),
                "class_counts": {label: corpus.labels.count(label) for label in ("ham", "spam")},
            }
            for corpus in corpora
        ],
        "comparisons": [compare_corpora(left, right) for left, right in combinations(corpora, 2)],
        "limitations": [
            "Similarity candidates require private review; they are not confirmed duplicates.",
            "Zero measured overlap does not establish independent sampling.",
            "No model scores, individual texts, row identifiers or template keys are reported.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for role in PUBLIC_IDS:
        parser.add_argument("--" + role.replace("_", "-"), type=Path)
    parser.add_argument("--include-synthetic", action="store_true", help="Audit tracked training and holdout fixtures.")
    args = parser.parse_args(argv)
    try:
        corpora = [load_corpus(role, [getattr(args, role)]) for role in PUBLIC_IDS if getattr(args, role) is not None]
        if args.include_synthetic:
            corpora.extend(
                [
                    load_corpus("synthetic_training", list(DEFAULT_SUPPLEMENTS)),
                    load_corpus("synthetic_holdout", [DEFAULT_HOLDOUT]),
                ]
            )
        report = audit(corpora)
    except (OSError, ValueError, csv.Error, UnicodeError):
        print("Corpus audit refused: check normalized inputs, provenance, and local resource limits.", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
