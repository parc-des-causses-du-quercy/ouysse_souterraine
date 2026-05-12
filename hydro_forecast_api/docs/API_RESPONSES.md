# API Responses — Contract reference

Authoritative reference for the shape of every response served by the Hydro Forecast API. Clients (C# orchestrator, scripts, dashboards) **must** rely on this document — not on inference from sample payloads — to define their deserialization models.

If you are extending the API and find yourself returning a shape that contradicts this document, **stop**: either update this document first (and align both sides), or fix the code so it conforms.

---

## 1. Universal envelope

The API uses two — and only two — top-level shapes:

- **Success**: a JSON object with the resource fields directly at the top level. There is *no* wrapping `{"data": ...}`.
- **Error**: `{"error": <ErrorObject>}`. Always at the HTTP envelope level. Never a string.

The `ErrorObject` is the same shape everywhere it appears (HTTP errors, task failures, validation):

```json
{
  "code":    "STRING",            // machine-readable identifier (see § 6)
  "message": "human-readable text",
  "details": <object | null>      // optional extra context, schema depends on `code`
}
```

`code` may be `null` for legacy task rows persisted before this contract — clients should treat `null` as "unknown" and fall back to dispatching on `message`.

---

## 2. Forecast lifecycle

Forecasts are asynchronous. The flow is:

```
POST /api/v1/points/{point_id}/forecast      → 202 Accepted, returns task_id
GET  /api/v1/tasks/{task_id}                  → poll until status ∈ {completed, failed}
```

Cadence recommendation: poll at 1-2 second intervals; typical forecast duration is 2-15s.

### 2.1 POST /api/v1/points/{point_id}/forecast

**Status 202 Accepted** (success):
```json
{
  "task_id":    "9fa042fa-ac16-49f9-b880-18c932bb3c92",
  "point_id":   "ouysse",
  "status":     "pending",
  "created_at": "2026-05-04T18:20:05.123456+00:00",
  "poll_url":   "/api/v1/tasks/9fa042fa-ac16-49f9-b880-18c932bb3c92"
}
```

**Status 404 / 422 / 429**: standard error envelope (§ 1).

### 2.2 GET /api/v1/tasks/{task_id}

The exact same fields are present for every task, but several are nullable depending on `status`. Clients should model **all** task fields as nullable and dispatch behavior on the `status` enum.

```json
{
  "id":               "9fa042fa-ac16-49f9-b880-18c932bb3c92",
  "point_id":         "ouysse",
  "status":           "pending" | "running" | "completed" | "failed",
  "created_at":       "ISO 8601 datetime",
  "started_at":       "ISO 8601 datetime | null",
  "completed_at":     "ISO 8601 datetime | null",
  "duration_seconds": <float | null>,
  "request":          <ForecastRequest | null>,
  "result":           <ForecastResult | null>,    // populated iff status=completed
  "error":            <ErrorObject | null>        // populated iff status=failed
}
```

| `status`      | `started_at` | `completed_at` | `duration_seconds` | `result` | `error` |
|---------------|--------------|----------------|--------------------|----------|---------|
| `pending`     | `null`       | `null`         | `null`             | `null`   | `null`  |
| `running`     | set          | `null`         | `null`             | `null`   | `null`  |
| `completed`   | set          | set            | set                | set      | `null`  |
| `failed`      | set          | set            | set                | `null`   | set     |

**Important**: `error` is **always** an `ErrorObject` (§ 1) when present. It is **never** a plain string. If a client model declares it as `string`, it will fail deserialization the first time a task fails. Define it as a nullable object matching `ErrorObject`.

### 2.3 GET /api/v1/tasks

```json
{
  "tasks": [<TaskObject>, ...],
  "count": <int>
}
```

Each `TaskObject` has the same shape as § 2.2.

### 2.4 DELETE /api/v1/tasks/{task_id}

**Success**: `200 OK` with `{"message": "Task deleted"}`.
**404**: error envelope.

---

## 3. ForecastResult schema (task.result when status=completed)

```json
{
  "forecast_date":          "2026-03-12T16:00:00",     // = lastQ_datetime echoed
  "offset_unit":            "hours",                   // always "hours" currently
  "arpege_reference_time":  "2026-03-12T12:00:00",     // ARPEGE run reference, or null
  "records": {
    "<sensor_name>": [[offset_hours_int, flow_m3_s_float], ...]
  },
  "metadata": {
    "assimilation_applied":  <bool>,
    "active_tributaries":    ["themines", "alzou"],
    "qsink_multiplier":      <float>,
    "state_was_reset":       <bool>,
    "reset_reason":          <string | null>
  }
}
```

**`records`** keys are sensor names. The outlet is keyed by `point_id` (e.g. `"ouysse"`); tributaries by their `basin_id` (e.g. `"themines"`, `"alzou"`).

**`records` values** are arrays of two-element arrays: `[offset_hours, flow_m3_s]`. `offset_hours` is an integer count of hours since the first record; multiply by 12 to get 5-minute steps if needed.

**`metadata.state_was_reset`** (bool, always present): `true` if the API auto-recovered from a stale state by resetting reservoirs to YAML defaults before this run. When `true`, forecasts at T+24h..T+96h may be degraded for 24-48h while the model reconverges. See `CONTRIBUTING.md § "Reprise après dérive d'état"`.

**`metadata.reset_reason`** (string|null): non-null iff `state_was_reset == true`. Human-readable explanation.

**`metadata.assimilation_applied`** is `true` if at least one `lastQ` was provided in the request.

---

## 4. Other endpoints (read-only)

### 4.1 GET /api/v1/points

```json
{
  "points": [
    {"point_id": "ouysse", "display_name": "Ouysse - Cabouy", "latitude": 44.74}
  ],
  "count": 1
}
```

### 4.2 GET /api/v1/points/{point_id}

Returns the full point YAML config as a JSON object. Schema follows `configs/points/{point_id}.yaml`. Top-level keys: `point_id`, `display_name`, `latitude`, `karstmod`, `tributaries`, `qsink_formula`.

### 4.3 GET /api/v1/points/{point_id}/sensors

```json
{
  "point_id": "ouysse",
  "inputs":  [{"sensor_name": "themines", "kind": "tributary"}, ...],
  "outputs": [{"sensor_name": "ouysse",   "kind": "outlet"}]
}
```

### 4.4 GET /api/v1/points/{point_id}/states

```json
{
  "point_id": "ouysse",
  "states": {
    "themines_gr4h": {"production_store": 0.35, "routing_store": 0.3, "uh1": [...], "uh2": [...], "state_time": "ISO datetime|null"},
    "karstmod":      {"wlE_final": -5.0, "C_final": 5.0, "M_final": 10.0, "state_time": "ISO datetime|null"}
  }
}
```

If no state has been persisted yet for a point, `states` is `{}`.

### 4.5 GET /api/v1/points/{point_id}/states/{component}

```json
{
  "point_id":  "ouysse",
  "component": "karstmod",
  "state":     <state object>
}
```

**404** if the component has no persisted state — error envelope.

---

## 5. Health & monitoring

| Endpoint | Status | Body |
|---|---|---|
| `GET /health`    | 200 | `{"status": "ok"}` |
| `GET /readiness` | 200 / 503 | `{"status": "ready" \| "not_ready", "checks": {...}}` |
| `GET /metrics`   | 200 | Prometheus text format (not JSON) |

---

## 6. Error code catalogue

Codes a client may legitimately encounter. The `code` is stable across versions; the `message` is human-readable and may vary. Dispatch on `code`, not `message`.

### 6.1 HTTP-level codes (in `error.code` of an HTTP error response)

| Code | HTTP | Meaning | Typical `details` |
|---|---|---|---|
| `NOT_FOUND`            | 404 | Generic resource not found | `null` |
| `POINT_NOT_FOUND`      | 404 | The `{point_id}` doesn't have a YAML config | `null` |
| `TASK_NOT_FOUND`       | 404 | The `{task_id}` doesn't exist | `null` |
| `VALIDATION_ERROR`     | 422 | Request body failed validation (e.g. missing `lastQ_datetime`) | message of the failed rule |
| `RATE_LIMITED`         | 429 | Rate limit hit (default `10/minute` on /forecast) | message from limiter |
| `INTERNAL_ERROR`       | 500 | Unhandled server-side exception | `null` |

### 6.2 Task-level codes (in `error.code` of a `failed` task)

| Code | Meaning | Recovery |
|---|---|---|
| `STATE_TOO_OLD_FOR_AUTO_RESET` | The persisted state is more than 7 days behind `lastQ_datetime`. The API refuses to auto-recover — manual reset required. See `CONTRIBUTING.md § "Reprise après dérive d'état"`. | Ops intervention only. Don't retry blindly. |
| `ForecastError`                | Generic forecast pipeline failure (e.g. ARPEGE fetch failed, no tributary results). The `message` carries the cause. | Retry after a short delay; escalate if persistent. |
| `StateAdvanceError`            | State advancement guard tripped. After auto-recovery was added, this should not normally reach the client (the API auto-resets and retries internally). If it does, treat as transient and check API logs. | Investigate API logs. |
| Any other Python exception type | Unexpected failure. `code` will be the exception class name. | Treat as `INTERNAL_ERROR`-equivalent. |

### 6.3 What a client should generally do

```
status == "completed"
    └─ consume result.records and result.metadata
       └─ if metadata.state_was_reset: surface a soft warning ("forecasts degraded for 24-48h")

status == "failed"
    ├─ error.code in {"STATE_TOO_OLD_FOR_AUTO_RESET"}     → page ops, don't retry
    ├─ error.code in {"VALIDATION_ERROR"}                 → fix request, don't retry as-is
    ├─ error.code in {"RATE_LIMITED"}                     → backoff and retry
    └─ everything else                                    → log + alert + retry with backoff
```

---

## 7. Versioning

This contract is implicitly v1 (matches the `/api/v1` route prefix). Breaking changes require a new prefix (`/api/v2/...`). The following are **not** breaking and may happen without notice:
- Adding new fields to existing objects.
- Adding new entries to error code catalogues.
- Adding new endpoints.

The following **are** breaking:
- Removing or renaming a field.
- Changing the type of a field (e.g. string → object — exactly the bug this document was created to prevent).
- Changing the meaning of an existing `code`.

---

## 8. Reference implementation patterns

### Polling a forecast task (pseudo-code)

```
POST /api/v1/points/{point_id}/forecast → { task_id, ... }

loop:
    response = GET /api/v1/tasks/{task_id}
    if response.status == "completed":
        return response.result
    if response.status == "failed":
        raise ApiException(response.error.code, response.error.message)
    sleep(1s)  # cap retries with a deadline (e.g. 60s)
```

### C#-style model sketch

```csharp
public class ErrorObject {
    public string Code { get; set; }
    public string Message { get; set; }
    public JToken Details { get; set; }   // shape varies per code
}

public class TaskObject {
    public string Id { get; set; }
    public string PointId { get; set; }
    public string Status { get; set; }                // "pending"|"running"|"completed"|"failed"
    public DateTime CreatedAt { get; set; }
    public DateTime? StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
    public double? DurationSeconds { get; set; }
    public ForecastRequest Request { get; set; }
    public ForecastResult Result { get; set; }        // null unless Status=="completed"
    public ErrorObject Error { get; set; }            // null unless Status=="failed"  ← MUST be object, not string
}
```

The **historical bug** that motivated this doc: clients had defined `Error` as `string` because failed-task responses were inadvertently serialized as strings. The API has been corrected (errors are now objects everywhere); clients must align their models accordingly.
