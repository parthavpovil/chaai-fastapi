# Async wraps for synchronous CPU + S3 I/O

PR6 of the Tier 1 scalability fix series. Routes PyPDF2 PDF parsing and every boto3 R2 call through `asyncio.to_thread` so neither freezes the event loop. Matches the existing pattern at `main.py:362-366` (R2 `head_bucket` for `/health`).

## Problem

Severity: **High** for any workload with concurrent document uploads or media transfers.

### Gap 1 — PyPDF2 freezes the event loop

[document_processor.py:72-103](backend/app/services/document_processor.py#L72) — `extract_text_from_pdf` calls `PyPDF2.PdfReader(...)` and per-page `extract_text()` directly. These are CPU-bound and synchronous: a 200-page PDF can take 5–15 s of pure CPU. While it runs, the worker's event loop is frozen — no HTTP, no WS, no Redis listener tick, no `/health` response. A single agent uploading a large training PDF effectively takes the whole worker offline for the duration.

The chain: `process_document(...)` and `reprocess_document(...)` (both `async def`) called `self.extract_text(...)` synchronously. With a `.pdf` argument that dispatched into `extract_text_from_pdf` → blocking PyPDF2.

### Gap 2 — boto3 blocks inside async R2 paths

[r2_storage.py](backend/app/services/r2_storage.py) — every `r2.put_object(...)` / `r2.delete_object(...)` call is synchronous boto3 (100–500 ms per call typical, multi-second over flaky links). All public R2 helpers are declared `async def` but the boto3 calls were direct, blocking the loop for the duration.

The audit noted the inconsistency: `main.py:362-366` already wraps `head_bucket` for `/health` in `run_in_executor` — but the upload/delete paths didn't.

## Root cause

Mixing sync libraries (boto3, PyPDF2) into async handlers without thread-pool off-loading. asyncio doesn't magically parallelize CPU-bound or blocking-IO calls — it requires explicit `asyncio.to_thread` (or `loop.run_in_executor`) to keep the event loop responsive.

## Fix

### PDF — wrap at the call site, not at the library boundary

`DocumentProcessor.extract_text_from_pdf` and `extract_text` remain **synchronous** (the property-test suite at [tests/test_property_document_processing.py](backend/tests/test_property_document_processing.py) calls them synchronously — changing the signature would break those tests). Both methods grew an explicit docstring warning that async callers must wrap them in `asyncio.to_thread`.

The two production async callers were updated:

```python
# process_document
file_ext = Path(filename).suffix.lower()
text_content = await asyncio.to_thread(self.extract_text, file_content, file_ext)

# reprocess_document
file_ext = Path(doc.name).suffix.lower()
text_content = await asyncio.to_thread(self.extract_text, file_bytes, file_ext)
```

`extract_text_from_txt` was intentionally **not** wrapped — it's just `.decode()` over an in-memory buffer (microseconds), faster than the to_thread scheduling overhead would cost. The dispatch in `extract_text` covers both file types in one call site.

### R2 — async public API, sync boto3 off-loaded via to_thread

All three `put_object` sites (in `download_and_store_whatsapp_media`, `upload_agent_media`, `upload_rag_document`) and the single `delete_object` site (in `delete_r2_object`) were converted to:

```python
r2 = _get_r2_client()
await asyncio.to_thread(
    functools.partial(
        r2.put_object,
        Bucket=settings.R2_BUCKET_NAME,
        Key=key,
        Body=file_bytes,
        ContentType=mime_type,
    )
)
```

`delete_r2_object` was changed from a sync `def` to `async def` for symmetry — callers in [document_processor.py:295](backend/app/services/document_processor.py#L295) and [embedding_service.py:247,337](backend/app/services/embedding_service.py) were updated to `await` it. (Both were already inside `async def` functions, so no further propagation was needed.)

## Why this approach

### `to_thread` over `aiobotocore` for R2

The audit's plan considered `aiobotocore` as a longer-term alternative. We chose `to_thread`:

- **Smaller diff.** One wrap per call site; no new dependency, no parallel API surface to learn.
- **`aiobotocore`'s drift from boto3 has burned teams in production.** Its release cadence trails boto3 and a subtle API mismatch can sneak in.
- **`to_thread` overhead is small relative to network I/O.** A `put_object` is dominated by the 100–500 ms round-trip; the executor scheduling adds microseconds.
- Migration to `aiobotocore` remains an option if executor saturation ever shows up in profiling — but at chaai's current load that's a hypothetical.

### `to_thread` at the call site, not inside `extract_text_from_pdf`

Two options were considered:

| Option | Pros | Cons |
|--------|------|------|
| Make `extract_text_from_pdf` `async` + use to_thread internally | Cleaner library boundary; callers don't need to remember | Breaks the existing property-test suite (sync calls) |
| Keep library sync; wrap at the two production async call sites | Tests unchanged; explicit wrapping documents intent | Two extra `to_thread` calls in user code |

The second option won — narrower blast radius, preserved tests, and the explicit wrapping at the call site makes it obvious to the reader that this path is CPU-heavy.

### `functools.partial` for the boto3 wraps

`asyncio.to_thread(func, *args, **kwargs)` would also work, but `to_thread` only forwards positional args naturally — `Bucket=…` kwargs become awkward. `functools.partial` keeps the call site readable and matches the existing pattern at `main.py:362-366`.

## Verification

### Local
- Parse check on all three modified files — clean.
- **PDF non-blocking test:** Start a worker. Upload a large (e.g. 100-page) PDF via the documents endpoint. From a separate client, hit `/health` repeatedly during the upload. Expect: `/health` p99 stays sub-100 ms throughout (event loop responsive). Before the fix, `/health` would have timed out (or returned multi-second latencies) for the duration of the PDF parse.
- **R2 non-blocking test:** Upload a 5 MB media file via the agent media endpoint. Simultaneously trigger a WS broadcast (e.g., have a customer message arrive). Expect: WS broadcast delivered within normal latency budget during the upload window, not blocked behind the boto3 put.
- **Delete-path regression test:** Delete a document with an R2 object. Expect: the R2 object is removed (verify in the R2 dashboard) and no exception about `'coroutine' was never awaited`.

### Production validation
- Watch the worker's event-loop slow-callback warnings (asyncio logs warnings when a callback takes >100 ms by default) — should drop noticeably after deploy.
- Worker CPU profile during a heavy PDF upload should now show the thread-pool worker (not the event-loop thread) consuming CPU.

### Tests
- The property-test suite at [tests/test_property_document_processing.py](backend/tests/test_property_document_processing.py) and [tests/test_property_document_round_trip.py](backend/tests/test_property_document_round_trip.py) — preserved unchanged. Their existing argument-type mismatch (passing a path string where bytes are expected) is a pre-existing issue separate from this PR.
- Existing R2 tests don't directly exercise the put/delete paths in unit-test form; the change is behaviorally equivalent (same boto3 calls, just off the event loop), so end-to-end tests that exercise the upload endpoints continue to pass.

## Files Changed

**Modified (3):**
- `backend/app/services/document_processor.py` — added `asyncio` import, expanded docstrings on `extract_text` / `extract_text_from_pdf` warning about sync nature, wrapped two production callers in `asyncio.to_thread`.
- `backend/app/services/r2_storage.py` — added `asyncio` + `functools` imports + module docstring; wrapped 3 `put_object` + 1 `delete_object` calls in `asyncio.to_thread(functools.partial(...))`. `delete_r2_object` changed from sync to async.
- `backend/app/services/embedding_service.py` — added `await` at the two `delete_r2_object` call sites.

## Related commits

(Single PR — commit SHA to be filled at merge.)

## Frontend impact

None. All response shapes and timings (from the user's perspective, both for document uploads and media handling) are unchanged — what changes is only whether other concurrent requests get served during the work.

## Follow-ups

- Consider a dedicated arq worker for document processing if concurrent upload volume grows enough that the web workers' thread pools (default ~40 threads) saturate. At current load this is not yet justified.
- If executor saturation ever shows up in flame graphs for R2 paths, evaluate `aiobotocore` migration as a Tier 3 / longer-term project.
- Tighten the property-test suite (separate cleanup, out of scope here) — it currently passes path strings where the implementation expects bytes; either fix or remove those tests.
