"""
Thread-safe in-memory cache for ARPEGE forecast datasets.

ARPEGE forecasts are published ~4 times/day (00h, 06h, 12h, 18h).
Between publications, the data is identical — caching avoids redundant
GRIB downloads which are the main performance bottleneck.
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

import logging
import threading
import time

logger = logging.getLogger(__name__)

# Default TTL: 6 hours (aligned with ARPEGE publication interval)
DEFAULT_TTL_HOURS = 6


class ArpegeCache:
    """Thread-safe in-memory cache for a single ARPEGE xr.Dataset."""

    def __init__(self, ttl_hours=DEFAULT_TTL_HOURS):
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_hours * 3600
        self._dataset = None
        self._ref_time = None
        self._fetched_at = 0.0

    def get_dataset(self):
        """Return cached (dataset, ref_time) if still valid, else None."""
        with self._lock:
            if self._dataset is None:
                return None
            age = time.time() - self._fetched_at
            if age > self._ttl_seconds:
                logger.info("ARPEGE cache expired", extra={
                    "age_seconds": round(age),
                    "ttl_seconds": self._ttl_seconds,
                })
                self._dataset = None
                self._ref_time = None
                return None
            logger.info("ARPEGE cache hit", extra={
                "ref_time": self._ref_time,
                "age_seconds": round(age),
            })
            return self._dataset, self._ref_time

    def get_stale_dataset(self):
        """Return cached dataset regardless of TTL (fallback on fetch failure)."""
        with self._lock:
            if self._dataset is None:
                return None
            logger.info("ARPEGE stale cache fallback", extra={
                "ref_time": self._ref_time,
                "age_seconds": round(time.time() - self._fetched_at),
            })
            return self._dataset, self._ref_time

    def set_dataset(self, ds, ref_time):
        """Store a freshly fetched dataset."""
        with self._lock:
            self._dataset = ds
            self._ref_time = ref_time
            self._fetched_at = time.time()
            logger.info("ARPEGE cache updated", extra={"ref_time": ref_time})

    def invalidate(self):
        """Force cache expiry (e.g. for testing)."""
        with self._lock:
            self._dataset = None
            self._ref_time = None


# Module-level singleton
_cache = ArpegeCache()


def get_cache():
    """Return the singleton ArpegeCache instance."""
    return _cache


def configure_cache(ttl_hours):
    """Reconfigure the singleton cache TTL (call at app init)."""
    global _cache
    _cache = ArpegeCache(ttl_hours=ttl_hours)
