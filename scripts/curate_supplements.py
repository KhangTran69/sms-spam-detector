"""Dedupe and de-template a synthetic supplement in place.

Rules (deterministic, first occurrence wins):
1. Drop exact and normalized duplicates (NFKC, case-fold, whitespace).
2. Group rows into template families by their first 30 normalized characters,
   with digits, peso signs, commas, and periods collapsed. Keep at most
   ``--max-per-family`` rows per family.
3. Record the family as ``group`` so group-aware splits keep the survivors together.

Usage: python scripts/curate_supplements.py data/raw/ph_supplement_2.csv --max-per-family 2
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path

import pandas as pd


def _normalized(message: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", message).casefold()).strip()


def family_key(message: str) -> str:
    return re.sub(r"[\d₱,.]+", "#", _normalized(message))[:30]


def curate(frame: pd.DataFrame, *, max_per_family: int) -> pd.DataFrame:
    work = frame.copy()
    work["_key"] = work["message"].astype(str).map(_normalized)
    work = work.drop_duplicates(subset="_key", keep="first")
    work["_family"] = work["message"].astype(str).map(family_key)
    work = work.groupby("_family", sort=False, group_keys=False).head(max_per_family)
    slug = work["_family"].str.replace(r"[^a-z0-9]+", "_", regex=True).str.strip("_")
    if "group" not in work.columns:
        work["group"] = "s2_" + slug
    else:
        work["group"] = work["group"].fillna("").astype(str)
        work.loc[work["group"].eq(""), "group"] = "s2_" + slug
    return work.drop(columns=["_key", "_family"]).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path)
    parser.add_argument("--max-per-family", type=int, default=2)
    args = parser.parse_args(argv)
    before = pd.read_csv(args.path, dtype=str, keep_default_na=False)
    after = curate(before, max_per_family=args.max_per_family)
    after.to_csv(args.path, index=False)
    print(
        f"{args.path}: {len(before)} -> {len(after)} rows; "
        f"labels {before['label'].value_counts().to_dict()} -> {after['label'].value_counts().to_dict()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
