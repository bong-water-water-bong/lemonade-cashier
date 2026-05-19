# Vision Pipeline

Architecture version: v3, spatial inventory intelligence and zone-aware
vision.

This document captures the Phase 2 vision direction for Lemonade Cashier.
It is intentionally a planning document, not a commitment to build vision
before the deterministic cashier core is stable.

Phase 1 remains text-first. Vision must eventually feed candidate events into
the same supervisor, confidence, safety, and audit paths that typed cashier
events use today.

## Goal

Build a local-first product onboarding and recognition pipeline for:

- getting store products into the local database
- intelligent product recognition
- UPC scanning
- OCR extraction
- visual SKU comparison
- spatial inventory awareness
- zone-aware deduction
- checkout assistance
- mobile capture
- remote device pairing

The first retail target is vape and convenience-store inventory, where
similar packaging, flavor variants, seals, warning labels, and disposable
device shapes make simple name matching unreliable.

The first user-facing job is not autonomous checkout. The first job is making
it easy for a store owner to create a high-quality local product database with
an iPhone, a simple booth, and a guided capture flow.

The next architectural step is spatial inventory intelligence. The system
should not only ask "what object is this?" It should ask "what object is this,
given the zone it came from?" A shelf or camera zone can narrow the candidate
set, improve confidence, reduce false positives, and make checkout faster.

## Hardware Stack

### Capture Device

Use an iPhone 15 Pro or Pro Max as the first capture device.

Useful capabilities:

- high-resolution still images
- barcode scanning
- OCR support
- LiDAR depth sensing
- ARKit measurement
- photogrammetry-friendly capture

### Capture Booth

Use a simple controlled booth:

- rotating platform
- fixed camera position
- stable LED lighting
- neutral matte background
- centered product placement

Matte white or matte gray backgrounds are preferred. Consistency matters more
than expensive hardware.

### Processing Node

Run processing on the local AMD Strix Halo Linux workstation:

- local inference
- local OCR
- local embeddings
- local vector database
- local audit trail

## Non-Goal

Do not buy or integrate enterprise 3D scanners in Phase 1 or early Phase 2.

The objective is controlled retail product fingerprinting, not perfect 3D
reconstruction. The rotating platform plus controlled lighting already gives
enough signal for retail-grade matching when combined with UPC, OCR,
embeddings, dimensions, and attendant confirmation.

## End-To-End Shape

```text
Store Cameras / iPhone Capture
    ->
Zone Detection Layer
    ->
Lemonade Vision Pipeline
    ->
OCR + Embeddings + UPC
    ->
Spatial Reasoning Engine
    ->
Vector Database
    ->
Checkout Agent
    ->
POS Decision Engine
```

The checkout agent may propose an item. It must not become the authority for
price, SKU, voids, refunds, or transaction close.

## Spatial Inventory Intelligence

Zone-aware matching lets Lemonade Cashier reason from location as well as
appearance. Each product candidate should be scored against the zone, shelf,
and camera context that produced the observation.

Example zones:

| Zone | Typical inventory |
| --- | --- |
| `ZONE_LEFT_TOBACCO` | cigarettes, single sticks, cigars, rolling tobacco |
| `ZONE_RIGHT_VAPE` | disposable vapes, e-liquid, pods, devices |
| `ZONE_COUNTER` | lighters, gum, accessories, impulse purchases |
| `ZONE_COOLER` | drinks and energy beverages |
| `ZONE_BACK_STOCK` | inventory-only storage |
| `ZONE_RESTRICTED` | controlled or attendant-only products |

Zone-aware deduction changes the search problem. If an object appears in
`ZONE_RIGHT_VAPE`, the matcher should prioritize vape embeddings, vape OCR
labels, vape SKU records, and vape confidence thresholds instead of searching
the full store inventory first.

## Zone System Design

Each store zone should eventually include:

```text
ZONE_ID
ZONE_NAME
CATEGORY_TYPES
CAMERA_IDS
SHELF_COORDINATES
RESTRICTED_RULES
CONFIDENCE_WEIGHTS
```

Example:

```json
{
  "zone_id": "ZONE_RIGHT_VAPE",
  "zone_name": "Right wall vape display",
  "categories": ["disposable_vapes", "e_liquid", "pods", "devices"],
  "camera_ids": ["CAM_RIGHT_01", "CAM_RIGHT_02"],
  "shelf_coordinates": ["SHELF_VAPE_01", "SHELF_VAPE_02", "SHELF_VAPE_03"],
  "restricted_rules": ["attendant_confirmation_for_low_confidence"],
  "confidence_weights": {
    "zone_match": 0.12,
    "shelf_match": 0.08
  }
}
```

## Store Camera Layer

Camera metadata should describe what each camera is supposed to prove.

```text
CAMERA_ID
ZONE_ID
FIELD_OF_VIEW
SHELF_TARGETS
POSITION
ANGLE
PURPOSE
```

Camera roles:

| Camera type | Purpose |
| --- | --- |
| Overhead cameras | customer movement, pickup tracking, zone transitions |
| Shelf cameras | product detection, shelf occupancy, stock level awareness |
| Checkout cameras | final product verification, barcode scanning, OCR validation |

The long-term product journey should be:

```text
Shelf zone
    ->
Customer pickup
    ->
Zone and shelf association
    ->
Checkout counter
    ->
Vision reconfirmation
    ->
POS decision
```

## Out-Of-Box Product Onboarding

The mobile capture flow should be the easiest way to add products to the local
database. A first-time user should be able to install Lemonade Cashier, pair an
iPhone, scan a product, and end with a draft product record without writing
CSV by hand.

Recommended first-run flow:

1. desktop starts the local capture API
2. desktop shows a pairing QR code
3. iPhone scans the QR code
4. operator scans the product UPC
5. operator captures front, back, sides, top, bottom, and close-up labels
6. app extracts barcode, OCR text, dimensions, colors, and embeddings
7. desktop shows a draft product record
8. operator confirms or edits brand, flavor, SKU, price, tax category, and
   aliases
9. confirmed record is written to the local product database
10. reference images and embeddings are indexed for future matching

The happy path should feel like inventory intake, not model training. Advanced
vision details belong behind the scenes.

Minimum viable onboarding fields:

- SKU or local item code
- UPC when present
- product name
- brand
- category
- price
- tax category
- aliases
- one or more reference images

Optional enriched fields:

- flavor
- supplier
- package size
- dimensions
- OCR text
- visual embedding IDs
- confidence threshold overrides

For vape retail, the UI should make flavor, nicotine strength, device type,
pack size, and disposable/pod/bottle category easy to enter because those are
common SKU differentiators.

## Capture Workflow

### Product Placement

The operator places the item on the rotating platform.

Requirements:

- matte background
- no strong reflections
- stable lighting
- fixed camera
- centered product

### Rotation Capture

The platform spins slowly while the iPhone captures either:

- 24 to 48 still images, or
- continuous video frames sampled into stills

The camera should not move during the rotation. Fixed capture improves
embeddings, OCR, dimension estimates, object recognition, and repeatability.

### Metadata Capture

After the rotation pass, capture close-up images for:

- UPC barcode
- warning labels
- flavor labels
- serial numbers
- seals
- ports
- top and bottom views

## Identification Signals

The product matcher should combine several independent signals:

| Signal | Purpose |
| --- | --- |
| UPC barcode | Exact SKU when available |
| OCR text | Brand, flavor, model, warnings, serial text |
| Visual embeddings | Packaging and device similarity |
| Dimensions | Size differentiation |
| Shape silhouette | Device and package shape |
| Color profile | Similar package family matching |
| Logo detection | Brand recognition |
| Zone match | Category and location prior from store layout |
| Shelf match | Product placement and historical shelf prior |

No single weak signal should silently add a product to checkout.

## Confidence Model

Each signal should produce an auditable confidence contribution.

Example:

| Signal | Example confidence |
| --- | --- |
| UPC match | 0.99 |
| OCR match | 0.86 |
| Visual match | 0.91 |
| Dimension match | 0.88 |
| Zone match | 0.97 |
| Shelf match | 0.93 |

The final confidence determines:

- automatic add when confidence is above policy threshold
- attendant verification when confidence is marginal
- rejection when evidence is insufficient

All low-confidence adds must remain visible in the event log and risk model.

Illustrative final score inputs:

```text
confidence =
  visual_match
  + UPC_match
  + OCR_match
  + dimension_match
  + zone_match
  + shelf_match
```

The implementation should use explicit weights and thresholds, not this raw
sum. The point is that location evidence becomes a first-class signal.

Example deduction:

```text
Object detected:
Camera: CAM_RIGHT_02
Zone: ZONE_RIGHT_VAPE
Shelf: SHELF_VAPE_03

Visual match: 0.84
OCR match: 0.77
Dimension match: 0.88
Zone match: 0.97

Result:
Likely disposable vape SKU, pending checkout reconfirmation.
```

## iPhone Measurement Layer

LiDAR and ARKit measurements can estimate:

- width
- height
- depth
- aspect ratio
- rough volume

This is useful for distinguishing similar vape products, package sizes, slim
vs. wide disposables, and short vs. tall SKU variants.

## Linux Processing Responsibilities

The local server is responsible for:

1. image ingestion
2. background removal
3. barcode detection
4. OCR extraction
5. embedding generation
6. dimension estimation
7. product matching
8. vector search
9. zone reasoning
10. shelf deduction
11. confidence calculation
12. metadata indexing

The processing path must be local-first. Cloud services require explicit
approval and must never receive sensitive transaction or customer data by
default.

## Candidate Stack

Keep implementation choices swappable behind small interfaces.

| Layer | Candidate tools |
| --- | --- |
| OCR | PaddleOCR, Tesseract |
| Embeddings | CLIP, OpenCLIP, SigLIP |
| Object detection | YOLOv8, YOLO-NAS |
| Tracking | ByteTrack, DeepSORT |
| Vector database | Qdrant, ChromaDB |
| API layer | FastAPI |
| Local LLM runtime | Lemonade Server, Ollama, vLLM |
| Evaluation | lemonade-eval |

Do not introduce these dependencies into the financial core.

## Evaluation Harness

Use [`lemonade-eval`](https://github.com/lemonade-sdk/lemonade-eval) as the
standard evaluation and benchmark harness for Lemonade-backed models.

The project already supports:

- loading models on a running Lemonade Server
- benchmarking time to first token and tokens per second
- prompting loaded models
- VLM benchmarking with an image input
- MMLU, HumanEval, perplexity, and lm-eval-harness accuracy tests
- Lemonade Server system information capture

Useful commands:

```bash
# Confirm the local Lemonade Server and machine profile.
lemonade-eval system-info --format json

# Load a model and benchmark text generation.
lemonade-eval -i Qwen3-4B-Instruct-2507-GGUF load bench

# Benchmark a vision-language model against a product image.
lemonade-eval -i Qwen3-4B-VL-FLM load bench \
  --image product-front.jpg \
  --image-size 1024x800 \
  -p "Identify visible brand, flavor, warning text, and package type." \
  --output-tokens 128
```

For the product onboarding pipeline, use `lemonade-eval` to answer practical
questions before promoting a model into the default local workflow:

- how fast does the model process one product image?
- how much image resizing is needed to fit context?
- does it reliably extract brand, flavor, warnings, and product type?
- is local VLM output useful enough to reduce manual typing?
- does the chosen model still work when Lemonade Server is offline from the
  public internet but local model files are cached?

The cashier app should keep its own deterministic tests for inventory, cart,
audit, and safety. `lemonade-eval` is for model and server behavior, not money
math.

## ngrok Pairing

ngrok is useful for fast mobile pairing and secure upload during development
and small-store deployment.

Each store or user must use their own ngrok account and authtoken. Do not
share one Lemonade-owned ngrok account across stores.

Reasons:

- avoids tunnel abuse
- avoids shared bandwidth limits
- limits credential exposure
- gives each operator control of their tunnel

## Setup Flow

Desktop setup should:

1. check if `ngrok` is installed
2. guide installation or auto-install where supported
3. check for an existing authtoken
4. ask the user to create or log in to ngrok if needed
5. save the token securely
6. launch the local Lemonade capture API
7. launch the ngrok tunnel
8. generate a QR code for mobile pairing

Useful commands:

```bash
ngrok config add-authtoken "$NGROK_AUTHTOKEN"
ngrok http http://localhost:8787
```

## Local Capture API

Proposed local endpoints:

```text
localhost:8787

/api/camera/session
/api/camera/upload
/api/product/capture
/api/product/barcode
/api/product/embedding
/api/product/search
/api/product/verify
/api/product/draft
/api/product/commit
/api/store/zones
/api/store/cameras
/api/store/shelves
```

These endpoints are not part of the deterministic cashier core. They should
produce candidate observations that the supervisor can accept, reject, or ask
the attendant to confirm.

For onboarding, `/api/product/draft` should assemble extracted signals into a
draft product record. `/api/product/commit` should only save after explicit
operator confirmation.

## Mobile Pairing

Recommended flow:

1. desktop generates a temporary pairing token
2. desktop creates a short-lived session
3. desktop displays a QR code
4. iPhone scans the QR code
5. iPhone uploads only into that authenticated session

Pairing sessions should expire after 5 to 10 minutes.

## Security Requirements

Mandatory controls:

- encrypted token storage
- temporary upload sessions
- QR-based pairing
- session expiration
- HTTPS-only uploads
- no anonymous uploads
- rate limiting
- audit logging

Mobile uploads should compress images intelligently, upload asynchronously,
retry failed uploads, and cache captures locally only when offline.

## Product Record Shape

Each product entry should eventually include enough metadata to support both
checkout and future re-identification.

Product metadata:

- SKU
- UPC
- category
- brand
- flavor
- aliases

Vision metadata:

- embeddings
- reference images
- OCR text
- dimension profile
- shape profile

Operational metadata:

- inventory
- pricing
- supplier
- confidence thresholds

Spatial metadata:

- preferred zone
- allowed zones
- preferred shelf
- historical positions
- zone confidence

Database rule:

The local product database must remain usable without the vision system. UPC,
name, price, tax category, and aliases are the checkout-critical fields.
Images, OCR, dimensions, embeddings, zone metadata, and shelf metadata improve
recognition but must not be required to ring up a product manually.

## Checkout Flow

During checkout:

1. track the product pickup zone when available
2. track product movement toward checkout when available
3. observe object on counter
4. attempt UPC scan
5. if UPC is unavailable, use OCR, embeddings, dimensions, zone, and shelf
   evidence
6. calculate confidence
7. auto-add only above policy threshold
8. request attendant confirmation below threshold

The cashier core remains the source of truth. Vision never writes price or
closes a transaction directly.

## Phase Boundaries

Phase 1:

- typed product events
- deterministic cart state
- subtotal, tax, total
- corrections
- local product database
- clear transaction state

Phase 2:

- stable image capture pipeline
- secure mobile uploads
- local OCR and barcode extraction
- local visual embeddings
- zone mapping
- inventory positioning
- shelf deduction
- product metadata quality
- candidate observations with confidence

Avoid for now:

- robotic automation
- enterprise scanners
- cloud infrastructure
- industrial camera systems
- real payment processing
- fully autonomous checkout

## Design Principle

The rotating platform and controlled lighting setup is the largest advantage
in the product onboarding pipeline. For in-store recognition, the largest
advantage is structured layout: controlled environments, known zones,
consistent shelf metadata, and spatial reasoning.

Consistency beats complexity in retail computer vision. Retail AI becomes
dramatically easier when the system understands where products belong.
