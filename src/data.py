"""Loading, validation, deduplication, and leakage-aware splitting of SMS data.

Design goals
------------
* One code path for base data, supplements, and holdouts.
* Fail loudly and actionably on schema/label/empty/class problems instead of
  silently dropping rows.
* Deduplicate *before* splitting and split by template/campaign group so
  near-identical templates cannot leak across train/validation/test.
* Emit file hashes and split fingerprints (never raw message text) so a model
  artifact can be traced back to exactly the data that produced it.

Optional metadata columns accepted in any CSV:
``source``, ``category`` (or ``message_type``/``type``), ``language``,
``labeling_confidence``, ``group`` (or ``template_family``/``campaign``), and
``received_at`` (or ``message_date``/``timestamp``) for temporal holdouts.
Missing metadata is filled with ``"unknown"``; it is never invented.
"""

from __future__ import annotations

from src.dataset_loading import (  # noqa: F401
    Dataset,
    FileRecord,
    _is_nan,
    _load_one,
    dataset_manifest,
    group_leakage_report,
    load_dataset,
    load_holdout,
    load_training_dataset,
    resolve_supplement_paths,
)

# Compatibility facade: the implementation lives in dataset_schema,
# dataset_loading, and dataset_splits. Every public and previously imported
# private name is re-exported so `from src.data import X` keeps working.
from src.dataset_schema import (  # noqa: F401
    CANONICAL_COLUMNS,
    DEFAULT_DATA,
    DEFAULT_HOLDOUT,
    DEFAULT_SEED,
    DEFAULT_SUPPLEMENTS,
    DEFAULT_TEST_SIZE,
    DEFAULT_VAL_SIZE,
    GROUP_KEY_VERSION,
    IMBALANCE_WARN_RATIO,
    LABEL_ALIASES,
    METADATA_COLUMNS,
    MIN_CLASS_COUNT,
    RAW_DIR,
    ROOT,
    VALID_LABELS,
    DatasetError,
    _column_lookup,
    _normalize_labels,
    _normalized_message_key,
    _read_csv,
    _resolve_message_and_label_columns,
    _resolve_metadata_columns,
    _sha256,
    make_group_key,
)
from src.dataset_splits import (  # noqa: F401
    Split,
    _class_present,
    _group_leakage,
    _stratified_random_split,
    _temporal_group_split,
    grouped_splits,
    split_dataset,
)
