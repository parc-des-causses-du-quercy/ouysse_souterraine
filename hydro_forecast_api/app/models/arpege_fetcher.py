"""
ARPEGE weather data fetcher — parameterized for any grid configuration.

Supports both real-time ARPEGE fetch and custom meteo data parsing.
Includes in-memory caching (TTL-based) and retry with backoff.
"""


# Copyright (c) 2025-2026 Synapse Informatique SARL — https://synapse-info.com
# Licence : propriétaire, voir LICENSE racine.
# SPDX-License-Identifier: LicenseRef-Synapse-Proprietary

import logging
import threading
import time
import warnings

import numpy as np
import pandas as pd
import pe_oudin
import xarray as xr
from meteofetch import Arpege01, Arpege025

from .arpege_cache import get_cache

# ---------------------------------------------------------------------------
# Workaround : Météo-France a migré son dépôt PNT (MinIO -> OVH) le 2026-05-12,
# cassant la `base_url_` hardcodée de meteofetch >=0.5,<1.0. Aucune version
# upstream corrigée à ce jour (signalé par PNR Causses du Quercy 2026-05-18).
# À retirer dès qu'une release meteofetch corrigée est publiée et épinglée
# dans requirements.txt. Arpege025 inclus en future-proof bien que non utilisé.
# ---------------------------------------------------------------------------
_OVH_BASE_URL = "https://meteofrance-pnt.s3.rbx.io.cloud.ovh.net/pnt"
for _cls in (Arpege01, Arpege025):
    if hasattr(_cls, "base_url_"):
        _cls.base_url_ = _OVH_BASE_URL

# Suppress cfgrib/xarray FutureWarnings about compat defaults
warnings.filterwarnings("ignore", category=FutureWarning, module="cfgrib")
warnings.filterwarnings("ignore", category=FutureWarning, module="xarray")

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15]  # seconds between retries
# Emit a heartbeat log every N seconds while the (synchronous, slow) ARPEGE
# network fetch is in progress, so operators don't think the worker is frozen.
# 30s is short enough to be reassuring on a 1-3min download, long enough not
# to spam the log file.
HEARTBEAT_INTERVAL_SECONDS = 30


def _fetch_one_attempt():
    """Single ARPEGE fetch attempt, wrapped with a heartbeat thread.

    `Arpege01.get_latest_forecast` blocks for typically 30-180s downloading
    GRIB files, with no progress callback. We spawn a daemon thread that
    logs `ARPEGE fetch still in progress | elapsed_seconds=...` every
    HEARTBEAT_INTERVAL_SECONDS until the call returns.
    """
    stop_event = threading.Event()
    start = time.time()

    def _heartbeat():
        while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
            logger.info("ARPEGE fetch still in progress", extra={
                "elapsed_seconds": round(time.time() - start, 1),
            })

    hb = threading.Thread(target=_heartbeat, name="arpege-heartbeat", daemon=True)
    hb.start()
    try:
        return Arpege01.get_latest_forecast(paquet="SP1", variables=("t2m", "tp"))
    finally:
        stop_event.set()


def _fetch_with_retry():
    """Fetch ARPEGE data with retry on transient failures.

    Each attempt is bracketed by start/end logs and emits periodic heartbeats
    so a long fetch doesn't look like a hung process to whoever is tailing
    the logs.
    """
    last_error = None
    for attempt in range(MAX_RETRIES):
        logger.info("ARPEGE network fetch starting (typical 30-180s)", extra={
            "attempt": attempt + 1,
            "max_retries": MAX_RETRIES,
        })
        try:
            return _fetch_one_attempt()
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BACKOFF[attempt]
                logger.warning("ARPEGE fetch failed, retrying", extra={
                    "attempt": attempt + 1,
                    "max_retries": MAX_RETRIES,
                    "delay_seconds": delay,
                    "error": str(e),
                })
                time.sleep(delay)
    raise last_error


def fetch_arpege_for_grids(grids, latitude):
    """
    Fetch ARPEGE forecast and compute weighted averages for multiple grids.

    Single ARPEGE API call, then spatial averaging per grid.

    Args:
        grids: dict of {component_name: {"indices": [...], "weights": [...]}}
        latitude: latitude in degrees for PE-Oudin calculation

    Returns:
        dict of {component_name: DataFrame} with columns
        [Date, precipitation, temperature, evapotranspiration]
    """
    t_total_start = time.time()

    # Check cache first
    cache = get_cache()
    cached = cache.get_dataset()
    cache_hit = cached is not None

    if cached is not None:
        ds, arpege_ref_time = cached
    else:
        # Cache miss — fetch with retry, fallback to stale cache on total failure
        logger.info("ARPEGE cache miss, fetching from API")
        try:
            t_fetch = time.time()
            ds_raw = _fetch_with_retry()
            logger.info("ARPEGE network fetch completed", extra={
                "duration_seconds": round(time.time() - t_fetch, 2),
            })

            t_parse = time.time()
            for k in ds_raw:
                ds_raw[k] = ds_raw[k].drop_vars("step", errors="ignore")
            ds = xr.Dataset(ds_raw)
            arpege_ref_time = str(pd.to_datetime(ds.time.values[0]))
            cache.set_dataset(ds, arpege_ref_time)
            logger.info("ARPEGE dataset parsed", extra={
                "duration_seconds": round(time.time() - t_parse, 2),
            })
        except Exception as e:
            # All retries failed — try stale cache as last resort
            stale = cache.get_stale_dataset()
            if stale is not None:
                ds, arpege_ref_time = stale
                logger.warning("Using stale ARPEGE cache after fetch failure", extra={
                    "ref_time": arpege_ref_time, "error": str(e),
                })
            else:
                raise

    results = {}

    for name, grid in grids.items():
        indices = np.array(grid["indices"])
        weights = np.array(grid["weights"])
        i_idx = indices[:, 0]
        j_idx = indices[:, 1]

        # Weighted spatial averaging
        tp_cumul = np.dot(ds.tp.values[:, i_idx, j_idx], weights)
        tp_hourly = np.maximum(np.diff(tp_cumul, prepend=0), 0)
        t2m = np.dot(ds.t2m.values[:, i_idx, j_idx], weights) - 273.15

        # PE-Oudin evapotranspiration
        times_list = pd.to_datetime(ds.time.values).to_pydatetime().tolist()
        ET = pe_oudin.PE_Oudin.pe_oudin(
            temp=t2m, time=times_list,
            lat=latitude, lat_unit="deg", out_units="mm/hour"
        )

        df = pd.DataFrame({
            "Date": ds.time.values,
            "precipitation": tp_hourly,
            "temperature": t2m,
            "evapotranspiration": np.array(ET),
        })
        df = df.dropna()
        results[name] = df

    logger.info("ARPEGE data processed", extra={
        "ref_time": arpege_ref_time,
        "components": list(results.keys()),
        "timesteps": len(next(iter(results.values()))) if results else 0,
        "cache_hit": cache_hit,
        "duration_seconds": round(time.time() - t_total_start, 2),
    })

    return results, arpege_ref_time


def parse_custom_meteo(custom_meteo_dict):
    """
    Parse custom meteorological data from API request body.

    Args:
        custom_meteo_dict: dict of {component_name: {
            "timestamps": [...],
            "precipitation_mm": [...],
            "temperature_c": [...],
            "evapotranspiration_mm": [...]
        }}

    Returns:
        dict of {component_name: DataFrame} with same format as fetch_arpege_for_grids
    """
    results = {}

    for name, data in custom_meteo_dict.items():
        df = pd.DataFrame({
            "Date": pd.to_datetime(data["timestamps"]),
            "precipitation": data["precipitation_mm"],
            "temperature": data["temperature_c"],
            "evapotranspiration": data["evapotranspiration_mm"],
        })
        df = df.dropna()
        results[name] = df

    logger.info("Custom meteo data parsed", extra={
        "components": list(results.keys()),
        "timesteps": len(next(iter(results.values()))) if results else 0,
    })

    return results, None
