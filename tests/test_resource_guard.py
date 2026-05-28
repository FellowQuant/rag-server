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


def test_auto_soft_limit_scales_for_model_baseline_without_allowing_runaway(
    monkeypatch,
) -> None:
    class Settings:
        indexer_worker_rss_soft_limit_mb = 0
        indexer_min_available_ram_mb = 512

    monkeypatch.setattr(
        "rag_server.worker.resource_guard.current_memory_snapshot",
        lambda: MemorySnapshot(rss_mb=1000, available_mb=36000),
    )
    guard = ResourceGuard.from_settings(Settings())

    assert guard._rss_soft_limit_mb == 18000

    snapshots = iter(
        [
            MemorySnapshot(rss_mb=9735, available_mb=28000),
            MemorySnapshot(rss_mb=32951, available_mb=6700),
            MemorySnapshot(rss_mb=32951, available_mb=6700),
        ]
    )
    guard._snapshot_provider = lambda: next(snapshots)
    guard._cleanup = lambda: None

    guard.checkpoint("docling-baseline")
    with pytest.raises(ResourceLimitExceeded, match="rss=32951 MB"):
        guard.checkpoint("runaway")
