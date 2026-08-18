"""Opaque data/metadata pair contract.

The contract deliberately does not decode either file. Source validation belongs
to the collector; downstream interpretation is outside the Frozen Layer 0 handoff.
"""

from .contract import (
    CONTRACT_REVISION,
    FileFact,
    select_published_release_assets,
    verify_draft_release_assets,
    verify_local_pair,
)
from .transport import DownloadedFile, StoredObject, download_asset, store_create_only

__all__ = [
    "CONTRACT_REVISION",
    "FileFact",
    "DownloadedFile",
    "StoredObject",
    "download_asset",
    "select_published_release_assets",
    "store_create_only",
    "verify_draft_release_assets",
    "verify_local_pair",
]
