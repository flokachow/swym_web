"""Where pictures of the swimmer live on disk, and how they are removed.

Annotated frames and evidence stills are images of a person. They are kept only
so the results page can show them, expire after `retentionHours`, and can be
deleted at any time. Uploaded videos are never kept: they are deleted as soon as
the analysis ends.
"""

from __future__ import annotations

import shutil
import time
import uuid

from . import config


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def prune(max_age_hours: float | None = None) -> int:
    """Delete runs older than the retention window. Returns how many went."""
    hours = config.load()["retentionHours"] if max_age_hours is None else max_age_hours
    cutoff = time.time() - hours * 3600
    removed = 0
    root = config.OVERLAY_ROOT
    if root.is_dir():
        for run in root.iterdir():
            try:
                if run.is_dir() and run.stat().st_mtime < cutoff:
                    shutil.rmtree(run, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
    # Uploads are deleted right after use; anything left is from a crash.
    up = config.UPLOAD_DIR
    if up.is_dir():
        for f in up.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < time.time() - 3600:
                    f.unlink()
            except OSError:
                continue
    return removed


def purge() -> int:
    """Delete every stored image and upload now."""
    count = 0
    for root in (config.OVERLAY_ROOT, config.UPLOAD_DIR):
        if root.is_dir():
            for item in root.iterdir():
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
                count += 1
    return count
