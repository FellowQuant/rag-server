"""Memory guard for ingestion workers."""

from __future__ import annotations

import gc
import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


class ResourceLimitExceeded(RuntimeError):
    """Raised when ingestion would continue under unsafe memory pressure."""


@dataclass(frozen=True)
class MemorySnapshot:
    rss_mb: float
    available_mb: float


def _default_cleanup() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def current_memory_snapshot() -> MemorySnapshot:
    import os

    import psutil

    process = psutil.Process(os.getpid())
    vm = psutil.virtual_memory()
    return MemorySnapshot(
        rss_mb=process.memory_info().rss / 1024 / 1024,
        available_mb=vm.available / 1024 / 1024,
    )


class ResourceGuard:
    def __init__(
        self,
        *,
        rss_soft_limit_mb: float,
        min_available_ram_mb: float,
        snapshot_provider: Callable[[], MemorySnapshot] = current_memory_snapshot,
        cleanup: Callable[[], None] = _default_cleanup,
    ) -> None:
        self._rss_soft_limit_mb = rss_soft_limit_mb
        self._min_available_ram_mb = min_available_ram_mb
        self._snapshot_provider = snapshot_provider
        self._cleanup = cleanup

    @classmethod
    def from_settings(cls, settings) -> "ResourceGuard":
        snapshot = current_memory_snapshot()
        rss_limit = settings.indexer_worker_rss_soft_limit_mb
        if rss_limit <= 0:
            rss_limit = min(8192, max(4096, snapshot.available_mb * 0.50))
        return cls(
            rss_soft_limit_mb=rss_limit,
            min_available_ram_mb=settings.indexer_min_available_ram_mb,
        )

    def checkpoint(self, label: str) -> None:
        snapshot = self._snapshot_provider()
        logger.info(
            "MEM [%s]: RSS=%.0f MB available=%.0f MB",
            label,
            snapshot.rss_mb,
            snapshot.available_mb,
        )
        if not self._is_unsafe(snapshot):
            return

        logger.warning(
            "MEM [%s]: unsafe memory snapshot, running cleanup before retry",
            label,
        )
        self._cleanup()
        retry = self._snapshot_provider()
        logger.info(
            "MEM [%s-after-cleanup]: RSS=%.0f MB available=%.0f MB",
            label,
            retry.rss_mb,
            retry.available_mb,
        )
        if self._is_unsafe(retry):
            raise ResourceLimitExceeded(
                "Memory unsafe at "
                f"{label}: rss={retry.rss_mb:.0f} MB "
                f"(limit={self._rss_soft_limit_mb:.0f} MB), "
                f"available={retry.available_mb:.0f} MB "
                f"(minimum={self._min_available_ram_mb:.0f} MB)"
            )

    def _is_unsafe(self, snapshot: MemorySnapshot) -> bool:
        return (
            snapshot.rss_mb > self._rss_soft_limit_mb
            or snapshot.available_mb < self._min_available_ram_mb
        )
