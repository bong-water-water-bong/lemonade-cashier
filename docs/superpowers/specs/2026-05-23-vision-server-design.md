# lemonade-vision-server — Design Spec

**Date:** 2026-05-23  
**Status:** approved  
**Scope:** v0.1 onboarding pipeline + customer deduction  
**Author:** brainstorming session

---

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Project location | New standalone repo `lemonade-vision-server` | Vision deps (CLIP, ChromaDB, FastAPI) are incompatible with cashier's stdlib-only core |
| Build order | Server first, iPhone app second | Hard ML unknowns are server-side; iPhone app is built against a known API |
| v0.1 scope | Onboarding only + customer deduction | Can't test matching without products in the DB; build in the right order |
| OCR / text extraction | Lemonade VLM (Qwen3.6-35B-A3B on :8001) | Already running with multimodal capability; replaces PaddleOCR in one pass |
| Barcode | pyzbar | Deterministic, fast, no ML required |
| Embeddings | CLIP / SigLIP (iGPU) | One pip install; runs locally; CLIP text encoder also handles deduction |
| Vector DB | ChromaDB (embedded) | Zero setup; single Python import; migrate to Qdrant if scale demands it |
| Product DB | SQLite | Stdlib-adjacent; no service; sufficient for single-store inventory |
| Tunnel | ngrok (per-operator account) | Already in spec; QR-code pairing; HTTPS enforced |

---

## Repo Structure

```
lemonade-vision-server/
  src/lemonade_vision/
    api/
      routes.py          # FastAPI routers
      session.py         # upload session management
    pipeline/
      barcode.py         # pyzbar UPC extraction
      vlm.py             # Qwen VLM client → :8001
      embeddings.py      # CLIP / SigLIP
      dimensions.py      # LiDAR depth → W×H×D
      background.py      # rembg background removal
    store/
      product_db.py      # SQLite product records
      vector_db.py       # ChromaDB embeddings
      image_store.py     # reference images on disk
    draft.py             # assemble draft record
    server.py            # FastAPI app + startup
  tests/
    test_barcode.py
    test_vlm.py
    test_pipeline.py
    test_routes.py
    test_session.py
    test_confidence.py
    test_dimensions.py
    fixtures/            # sample images, depth JSON, narration WAV
  Makefile
  pyproject.toml
  ngrok.sh               # tunnel launcher
```

### Runtime Service Map

```
iPhone (SwiftUI app)
    ↓ HTTPS · X-Session-Token · ngrok tunnel
lemonade-vision-server :8787    ← this repo
    ↓ HTTP :8001
Lemonade llama-server :8001     ← already running (Qwen3.6-35B-A3B, multimodal)
    ↓ CameraSource.observations() protocol
lemonade-cashier                ← existing repo, sensors.camera + sensors.speech stubs
```

---

## API Endpoints

All requests after `/session/start` require `X-Session-Token: {session_id}` header.

### Session

| Method | Path | Purpose |
|---|---|---|
| POST | `/session/start` | Create 10-min upload session → returns `session_id` + QR code PNG (base64) |
| DELETE | `/session/{id}` | Close session, clean up tmp buffer |

### Capture (iPhone booth scan)

| Method | Path | Purpose |
|---|---|---|
| POST | `/capture/video` | Upload raw rotation video (4K HEVC/H.264, ~100–200 MB for 15s). Server extracts ~36 frames (1 per 0.33s), discards blurry frames (Laplacian variance threshold), keeps sharpest per 30° sector. |
| POST | `/capture/still` | Upload one close-up still (JPEG/HEIC) with `angle` label (upc/label/top/bottom) — for the precision shots taken after the rotation pass → returns `frame_id` |
| POST | `/capture/depth` | Upload LiDAR depth map (ARKit `.depth` or JSON float array) linked to `frame_id` from `/capture/still`. Taken on the UPC shot at known 35 cm distance for dimension baseline. |
| POST | `/capture/audio` | Upload narration WAV/M4A recorded during rotation pass — transcript injected into VLM prompt at finalize time |
| POST | `/capture/finalize` | Signal end of capture pass — triggers full processing pipeline → returns `job_id` |

### Product (draft + confirm)

| Method | Path | Purpose |
|---|---|---|
| GET | `/product/draft/{job_id}` | Poll processing result — returns draft: UPC, brand, flavor, OCR text, dimensions, embedding ID, reference image URLs, per-signal confidence scores |
| POST | `/product/commit` | Operator confirms (or edits) draft → writes to SQLite + ChromaDB + disk → returns committed `sku` |
| PATCH | `/product/{sku}` | Edit committed product (fix brand typo, add alias, update price) — no reprocessing |

### Deduction (customer speech → SKU)

| Method | Path | Purpose |
|---|---|---|
| POST | `/deduce/text` | Body: `{"query": "blue elf bar mango 5000", "top_k": 3}` — VLM extracts intent + signals, embeds query, searches ChromaDB, re-ranks, returns candidates with confidence and match reason |
| POST | `/deduce/audio` | Body: multipart WAV/M4A — transcribed via fw-server :8004 (faster-whisper), then runs `/deduce/text` pipeline |

### Utility

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Server status + VLM :8001 reachable + ChromaDB collection count |
| GET | `/pairing/qr` | Regenerate QR code for existing session |

---

## Data Flow

### Path A — Booth Onboarding

```
iPhone (4K video + LiDAR depth + narration audio)
    ↓ /capture/video  (raw rotation video — server extracts frames)
    ↓ /capture/still  (×5 close-up: upc/label/top/bottom)
    ↓ /capture/depth  (LiDAR on UPC still for dimensions)
    ↓ /capture/audio  (narration recorded during rotation)
    ↓ /capture/finalize
Processing pipeline (sequential):
    1. Background removal (rembg)
    2. Barcode detection (pyzbar) → UPC or null
    3. Transcribe narration → fw-server :8004 → text hint
    4. VLM prompt: front + UPC frames + narration transcript
       → brand · flavor · OCR text · category · warnings · puff count
    5. CLIP embedding (front + UPC frames)
    6. LiDAR depth → W × H × D estimate
    7. Assemble draft record + per-signal confidence scores
    ↓ /product/draft/{job_id}  (operator polls)
Operator reviews pre-filled draft, edits if needed
    ↓ /product/commit
Written to:
    SQLite    → product metadata
    ChromaDB  → visual + text embeddings
    Disk      → reference images (800px max, 85% JPEG)
```

### Path B — Customer Request Deduction

```
Customer: "give me a blue elf bar mango ice"
    ↓ audio → /deduce/audio → fw-server :8004 → transcript
    OR typed text → /deduce/text directly
/deduce/text pipeline:
    1. VLM prompt: extract brand · flavor · size · color · category
    2. Embed structured query → CLIP text vector
    3. ChromaDB product_text collection: top_k similarity search
    4. Re-rank: exact brand/flavor/alias match bonus
    5. Return: [{sku, confidence, match_reason}, ...]
    ↓ confidence-scored candidates → lemonade-cashier supervisor gate
    High → propose cart add
    Medium → attendant confirmation
    Low → manual entry fallback
All deduction events written to cashier JSONL event log.
```

---

## Booth Capture Guide

### Physical Setup

- **iPhone 15 Pro Max** in DJI Osmo, mounted on clamp or mini-tripod — **do not hand-hold**. Camera must be completely fixed.
- **Distance:** 30–45 cm product to lens. Product fills ~60% of frame.
- **Lighting:** LED lights at 45° from both sides, diffused (not direct — foil packaging glares).
- **Background:** matte white or matte gray behind product.
- **Center mark:** gaffer tape cross (matte black on light platform, matte white on dark) at turntable center. Consistent placement = consistent LiDAR dimensions across all scans.

### Scan Sequence (~60 seconds per product)

1. **Place product** on center mark. Front label (most branded face) facing camera at 0°.
2. **Start session** in app → QR paired → session token active.
3. **Record rotation video** (4K HEVC + LiDAR depth simultaneous). Spin platform slowly by hand — one full rotation in 10–15 seconds. While spinning: **narrate** ("This is a Lost Mary OS5000, watermelon ice, 13 mL, 50 mg, the tall skinny one."). App uploads video to `/capture/video` and audio to `/capture/audio`.
4. **Guided close-up stills**: app prompts through UPC → warning label → flavor label → top → bottom. One tap per angle → `/capture/still`. LiDAR depth captured on UPC shot → `/capture/depth`.
5. **Tap Done** → `/capture/finalize`. Server extracts ~36 frames from rotation video (1 per 0.33s), discards blurry frames (Laplacian variance threshold), keeps sharpest per 30° sector.
6. **Review draft** on phone. Pre-filled from narration + VLM + barcode. Minimal editing expected.
7. **Confirm** → product committed.

### Product Pose Rules

- Upright with mouthpiece/top pointing up. Base flat on platform. No lean.
- Widest label face toward camera at 0°.
- For flat products (cartons, pouches): stand on narrow edge; widest face to camera. Use foam block if needed.
- Remove price stickers and temporary labels before scanning.
- Scan sealed/unopened product only.
- Do not hold the platform during rotation — spin with a flick, keep hands out of frame.

---

## Database Schema

### SQLite

**`products`**

| Column | Type | Notes |
|---|---|---|
| `sku` | TEXT PK | Local item code, operator-assigned |
| `upc` | TEXT | Null if no barcode |
| `brand` | TEXT | e.g. "Elf Bar" |
| `flavor` | TEXT | e.g. "Mango Ice" |
| `category` | TEXT | disposable_vape · e_liquid · pod · device … |
| `puff_count` | INTEGER | 3500 / 5000 / 10000 — primary SKU differentiator |
| `nicotine_mg` | INTEGER | 35 / 50 — used by age-gate confidence rules |
| `ocr_text` | TEXT | Raw extracted label text blob |
| `narration` | TEXT | Operator booth transcript (searchable) |
| `width_mm` | REAL | From LiDAR |
| `height_mm` | REAL | From LiDAR |
| `depth_mm` | REAL | From LiDAR |
| `confidence_threshold` | REAL | Per-SKU override (default 0.85) |
| `requires_attendant` | BOOLEAN | Always-verify flag for age-restricted SKUs |
| `created_at` | TEXT | ISO-8601 UTC |
| `updated_at` | TEXT | ISO-8601 UTC |

**`product_aliases`** — `sku` FK + `alias` TEXT. Populated from narration and operator edits. Searched in `/deduce/text` re-rank step.

**`product_images`** — `sku` FK + `angle` TEXT + `path` TEXT + `is_primary` BOOLEAN.

**`capture_sessions`** — `session_id` UUID PK + `tmp_dir` + `expires_at` + `frame_count` + `narration_path`.

**`draft_jobs`** — `job_id` PK + `status` (processing/ready/committed/discarded) + `draft_json` blob + `signal_scores` JSON blob + `created_at`.

### ChromaDB Collections

**`product_visual`** — CLIP 512-dim embeddings from front + UPC frames. ID: `{sku}_{angle}`. Metadata: sku, brand, category. Used by Phase B checkout camera matching.

**`product_text`** — CLIP text encoder embeddings from `"brand flavor category aliases"` string. ID: `sku`. Metadata: sku, brand, flavor, category, puff_count. Primary collection hit by `/deduce/text`.

### Disk Layout

```
data/
  images/
    {sku}/
      front.jpg     # 800px max, 85% quality
      upc.jpg
      rear.jpg
      {angle}.jpg
  sessions/         # tmp, auto-cleaned on expiry
  products.db       # SQLite
  chroma/           # ChromaDB embedded store
```

---

## Error Handling

| Failure | Onboarding behaviour | Deduction behaviour |
|---|---|---|
| VLM :8001 unreachable | Draft returned with `vlm_status: "unavailable"` — UPC + narration fields filled, brand/flavor blank for operator to type. Timeout: 15s. | Returns 503 immediately. Cashier falls to manual entry. Timeout: 3s. |
| No barcode detected | `upc: null` — not an error. Confidence model applies zero weight to barcode signal. | N/A |
| No depth data uploaded | Dimension fields null. Confidence model skips dimension signal. Product still commitable. | N/A |
| fw-server :8004 unreachable | Narration skipped (`narration: null`). VLM gets images only. | `/deduce/audio` returns 503. Use `/deduce/text` with typed query. |
| Session expired mid-capture | All uploaded frames + audio deleted. iPhone receives 401. Operator starts new session. No partial data leaks. | N/A |

**Hard rules:**
- All service calls have explicit timeouts. Nothing blocks indefinitely.
- VLM and fw-server failures return structured error shapes, never raise through the API.
- No silent failures — every degraded path is logged and surfaced in the response.

---

## Testing

### Pyramid

**Unit tests** (fast, no network):
- `test_barcode.py` — pyzbar against fixture images with known UPCs
- `test_dimensions.py` — LiDAR depth array → W×H×D math
- `test_draft.py` — draft assembly from mock signal outputs
- `test_session.py` — session expiry, token validation, cleanup
- `test_confidence.py` — weighted score math, threshold branching

**API tests** (FastAPI TestClient, services mocked):
- `test_routes.py` — all endpoints: auth, session lifecycle, upload, finalize, commit, deduce
- VLM and fw-server replaced with pytest fixtures returning fixed outputs
- Asserts correct 4xx on expired session, missing token, bad angle label

**Integration tests** (real services, auto-skipped if :8001 unreachable):
- `test_vlm.py` — real call to :8001 with sample vape image, assert brand/flavor extracted
- `test_embeddings.py` — CLIP encode, store in ChromaDB, query back
- `test_pipeline.py` — end-to-end: fixture frames → finalize → assert draft fields populated

### Fixtures

- `fixtures/elf-bar-front.jpg` — real product image for VLM + barcode tests
- `fixtures/depth-sample.json` — synthetic LiDAR depth array
- `fixtures/narration.wav` — 10s sample operator narration

**All tests write to `/tmp` — never to `data/`.** (Inherited from lemonade-cashier rule.)

### Make Targets

```sh
make lint            # ruff
make type            # pyright
make test            # unit + API (no network required)
make test-integration  # requires :8001 live
make all             # lint + type + test
```

---

## Cashier Integration Points

- `sensors/camera.py` — `CameraSource.observations()` protocol. The vision server's `/deduce` output is shaped into `Observation` events during Phase B (checkout recognition). Out of scope for v0.1 but the interface is already defined.
- `sensors/speech.py` — stub filled by calling `/deduce/text` with transcribed customer speech from fw-server.
- All vision-originated events enter the cashier through the supervisor confidence gate — never directly into the cart.
- Price, SKU authority, voids, refunds remain in the cashier core. The vision server is a candidate source only.

---

## Out of Scope for v0.1

- Checkout recognition (live counter camera matching) — Phase B
- Zone / shelf awareness — Phase B
- iPhone SwiftUI app — built after server API is stable
- PoE store cameras — Phase B
- Shelf monitoring, theft detection, customer tracking — Phase 2+
- Cloud infrastructure of any kind
