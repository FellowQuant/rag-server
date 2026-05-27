from __future__ import annotations

import pytest

from rag_server.worker.resource_guard import (
    MemorySnapshot,
    ResourceGuard,
    ResourceLimitExceeded,
)


def test_resource_guard_allows_safe_memory_snapshot() -> None:
    guard = ResourceGuard(
        rss_soft_limit_mb=1024,
        min_available_ram_mb=512,
        snapshot_provider=lambda: MemorySnapshot(rss_mb=100, available_mb=2048),
    )

    guard.checkpoint("safe")


def test_resource_guard_raises_after_gc_when_memory_remains_unsafe() -> None:
    snapshots = iter(
        [
            MemorySnapshot(rss_mb=4096, available_mb=128),
            MemorySnapshot(rss_mb=4096, available_mb=128),
        ]
    )
    guard = ResourceGuard(
        rss_soft_limit_mb=1024,
        min_available_ram_mb=512,
        snapshot_provider=lambda: next(snapshots),
        cleanup=lambda: None,
    )

    with pytest.raises(ResourceLimitExceeded, match="unsafe"):
        guard.checkpoint("after-parse")
