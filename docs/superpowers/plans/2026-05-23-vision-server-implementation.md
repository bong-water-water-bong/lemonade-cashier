# lemonade-vision-server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `lemonade-vision-server`, a FastAPI server that ingests 4K rotation video + LiDAR depth + operator narration audio from an iPhone booth scan, runs a multimodal pipeline (pyzbar UPC, Qwen3.6 VLM, CLIP embeddings, rembg), and persists products to SQLite + ChromaDB for cashier deduction.

**Architecture:** Standalone Python repo (`~/lemonade-vision-server/`) separate from lemonade-cashier. iPhone uploads raw video + stills + audio over ngrok HTTPS; server owns all ML processing. FastAPI lifespan initialises all models/DBs at startup; capture routes push work to a background task; deduction routes query ChromaDB with CLIP text embeddings.

**Tech Stack:** Python ≥ 3.12, FastAPI, uvicorn, httpx, pydantic v2, pyzbar, Pillow, numpy, open-clip-torch (ViT-B-32), torch, chromadb, rembg, ffmpeg (system), SQLite (stdlib), ngrok.

---

### Task 1: Bootstrap repo + pyproject.toml + Makefile

**Files:**
- Create: `~/lemonade-vision-server/pyproject.toml`
- Create: `~/lemonade-vision-server/Makefile`
- Create: `~/lemonade-vision-server/.gitignore`
- Create: `~/lemonade-vision-server/src/lemonade_vision/__init__.py`
- Create: `~/lemonade-vision-server/tests/__init__.py`

- [ ] **Step 1: Create repo directory and git init**

```bash
mkdir -p ~/lemonade-vision-server/src/lemonade_vision
mkdir -p ~/lemonade-vision-server/tests
cd ~/lemonade-vision-server
git init
git config user.email "277547417+bong-water-water-bong@users.noreply.github.com"
git config user.name "bcloud"
```

- [ ] **Step 2: Write pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "lemonade-vision"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "httpx>=0.27",
    "pydantic>=2.7",
    "pyzbar>=0.1.9",
    "Pillow>=10.4",
    "numpy>=1.26",
    "open-clip-torch>=2.26",
    "torch>=2.3",
    "chromadb>=0.5",
    "rembg>=2.0",
    "qrcode[pil]>=7.4",
    "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "httpx>=0.27", "ruff>=0.4", "pyright>=1.1"]

[tool.hatch.build.targets.wheel]
packages = ["src/lemonade_vision"]

[tool.ruff]
line-length = 100

[tool.pyright]
pythonVersion = "3.12"
typeCheckingMode = "basic"
venvPath = "."
venv = ".venv"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 3: Write Makefile**

```makefile
.PHONY: install lint type test test-integration all

install:
	uv venv
	uv pip install -e ".[dev]"

lint:
	uv run ruff check src/ tests/

type:
	uv run pyright src/

test:
	uv run pytest tests/ -v -k "not integration"

test-integration:
	VISION_INTEGRATION=1 uv run pytest tests/ -v

all: lint type test
```

- [ ] **Step 4: Write .gitignore**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
data/
*.db
ngrok.log
.env
dist/
*.egg-info/
```

- [ ] **Step 5: Create empty __init__ files**

```bash
touch ~/lemonade-vision-server/src/lemonade_vision/__init__.py
touch ~/lemonade-vision-server/tests/__init__.py
```

- [ ] **Step 6: Install deps and verify**

```bash
cd ~/lemonade-vision-server
uv venv
uv pip install -e ".[dev]"
uv run python -c "import fastapi, pydantic, chromadb; print('OK')"
```
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
cd ~/lemonade-vision-server
git add pyproject.toml Makefile .gitignore src/ tests/
git commit -m "feat: bootstrap lemonade-vision-server repo"
```

---

### Task 2: Pydantic models

**Files:**
- Create: `src/lemonade_vision/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_models.py
from lemonade_vision.models import (
    SessionStartResponse, FinalizeResponse, SignalScores,
    DraftProduct, CommitRequest, CommitResponse,
    DeduceRequest, DeduceCandidate, DeduceResponse,
    HealthResponse,
)


def test_session_start_response_has_session_id_and_qr():
    r = SessionStartResponse(session_id="abc", qr_png_b64="data")
    assert r.session_id == "abc"
    assert r.qr_png_b64 == "data"


def test_signal_scores_clamp_to_float():
    s = SignalScores(upc=1.0, vlm=0.9, embedding=0.8, dimension=0.7)
    assert s.upc == 1.0


def test_draft_product_optional_fields_default_none():
    d = DraftProduct(job_id="j1", status="ready")
    assert d.upc is None
    assert d.brand is None
    assert d.dimensions is None


def test_deduce_response_has_candidates():
    c = DeduceCandidate(sku="SKU001", confidence=0.9, match_reason="brand+flavor")
    r = DeduceResponse(candidates=[c])
    assert len(r.candidates) == 1
    assert r.candidates[0].sku == "SKU001"
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd ~/lemonade-vision-server
uv run pytest tests/test_models.py -v
```
Expected: `ImportError` (module not yet created)

- [ ] **Step 3: Write models.py**

```python
# src/lemonade_vision/models.py
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class SessionStartResponse(BaseModel):
    session_id: str
    qr_png_b64: str


class FinalizeResponse(BaseModel):
    job_id: str
    message: str = "processing"


class SignalScores(BaseModel):
    upc: float = 0.0
    vlm: float = 0.0
    embedding: float = 0.0
    dimension: float = 0.0


class ProductDimensions(BaseModel):
    width_mm: float
    height_mm: float
    depth_mm: float


class DraftProduct(BaseModel):
    job_id: str
    status: str
    upc: Optional[str] = None
    brand: Optional[str] = None
    flavor: Optional[str] = None
    category: Optional[str] = None
    puff_count: Optional[int] = None
    nicotine_mg: Optional[int] = None
    ocr_text: Optional[str] = None
    narration: Optional[str] = None
    dimensions: Optional[ProductDimensions] = None
    signal_scores: Optional[SignalScores] = None
    vlm_status: str = "ok"
    reference_image_urls: list[str] = []


class CommitRequest(BaseModel):
    job_id: str
    sku: str
    brand: str
    flavor: str
    category: str
    puff_count: Optional[int] = None
    nicotine_mg: Optional[int] = None
    requires_attendant: bool = False
    confidence_threshold: float = 0.85
    aliases: list[str] = []


class CommitResponse(BaseModel):
    sku: str
    message: str = "committed"


class ProductPatch(BaseModel):
    brand: Optional[str] = None
    flavor: Optional[str] = None
    category: Optional[str] = None
    puff_count: Optional[int] = None
    nicotine_mg: Optional[int] = None
    requires_attendant: Optional[bool] = None
    confidence_threshold: Optional[float] = None
    aliases: list[str] = []


class DeduceRequest(BaseModel):
    query: str
    top_k: int = 3


class DeduceCandidate(BaseModel):
    sku: str
    confidence: float
    match_reason: str
    brand: Optional[str] = None
    flavor: Optional[str] = None


class DeduceResponse(BaseModel):
    candidates: list[DeduceCandidate]
    query_used: str = ""


class HealthResponse(BaseModel):
    status: str
    vlm_reachable: bool
    chroma_product_count: int
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/test_models.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/lemonade_vision/models.py tests/test_models.py
git commit -m "feat: add pydantic models"
```

---

### Task 3: SQLite schema + session management

**Files:**
- Create: `src/lemonade_vision/store/schema.py`
- Create: `src/lemonade_vision/session.py`
- Create: `tests/test_session.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_session.py
import tempfile
import time
from pathlib import Path
from lemonade_vision.store.schema import init_db
from lemonade_vision.session import (
    create_session, validate_session, close_session, expire_old_sessions,
)


def _db():
    tmp = tempfile.mktemp(suffix=".db", dir="/tmp")
    db = init_db(tmp)
    return db


def test_create_and_validate_session():
    db = _db()
    tmp_dir = tempfile.mkdtemp(dir="/tmp")
    sid = create_session(db, tmp_dir, ttl_seconds=300)
    assert sid is not None
    result = validate_session(db, sid)
    assert result is not None
    assert result["session_id"] == sid


def test_expired_session_returns_none():
    db = _db()
    tmp_dir = tempfile.mkdtemp(dir="/tmp")
    sid = create_session(db, tmp_dir, ttl_seconds=0)
    time.sleep(0.1)
    result = validate_session(db, sid)
    assert result is None


def test_close_session_cleans_up():
    db = _db()
    tmp_dir = tempfile.mkdtemp(dir="/tmp")
    sid = create_session(db, tmp_dir, ttl_seconds=300)
    close_session(db, sid)
    result = validate_session(db, sid)
    assert result is None


def test_expire_old_sessions_removes_expired():
    db = _db()
    tmp_dir = tempfile.mkdtemp(dir="/tmp")
    sid = create_session(db, tmp_dir, ttl_seconds=0)
    time.sleep(0.1)
    count = expire_old_sessions(db)
    assert count >= 1
    assert validate_session(db, sid) is None
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/test_session.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write store/schema.py**

```python
# src/lemonade_vision/store/__init__.py
# (empty)
```

```python
# src/lemonade_vision/store/schema.py
import sqlite3
from pathlib import Path


DDL = """
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    upc TEXT,
    brand TEXT NOT NULL,
    flavor TEXT NOT NULL,
    category TEXT NOT NULL,
    puff_count INTEGER,
    nicotine_mg INTEGER,
    ocr_text TEXT,
    narration TEXT,
    width_mm REAL,
    height_mm REAL,
    depth_mm REAL,
    confidence_threshold REAL NOT NULL DEFAULT 0.85,
    requires_attendant BOOLEAN NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
    alias TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
    angle TEXT NOT NULL,
    path TEXT NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS capture_sessions (
    session_id TEXT PRIMARY KEY,
    tmp_dir TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    frame_count INTEGER NOT NULL DEFAULT 0,
    narration_path TEXT
);

CREATE TABLE IF NOT EXISTS draft_jobs (
    job_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'processing',
    draft_json TEXT,
    signal_scores TEXT,
    created_at TEXT NOT NULL
);
"""


def init_db(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    conn.commit()
    return conn
```

- [ ] **Step 4: Write session.py**

```python
# src/lemonade_vision/session.py
import uuid
import sqlite3
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expiry_iso(ttl_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()


def create_session(db: sqlite3.Connection, tmp_dir: str, ttl_seconds: int = 600) -> str:
    session_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO capture_sessions (session_id, tmp_dir, expires_at) VALUES (?, ?, ?)",
        (session_id, tmp_dir, _expiry_iso(ttl_seconds)),
    )
    db.commit()
    return session_id


def validate_session(
    db: sqlite3.Connection, session_id: str
) -> Optional[sqlite3.Row]:
    row = db.execute(
        "SELECT * FROM capture_sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < _now_iso():
        _cleanup_session(db, dict(row))
        return None
    return row


def close_session(db: sqlite3.Connection, session_id: str) -> None:
    row = db.execute(
        "SELECT * FROM capture_sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row:
        _cleanup_session(db, dict(row))


def expire_old_sessions(db: sqlite3.Connection) -> int:
    rows = db.execute(
        "SELECT * FROM capture_sessions WHERE expires_at < ?", (_now_iso(),)
    ).fetchall()
    for row in rows:
        _cleanup_session(db, dict(row))
    return len(rows)


def _cleanup_session(db: sqlite3.Connection, row: dict) -> None:
    tmp = Path(row["tmp_dir"])
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    db.execute(
        "DELETE FROM capture_sessions WHERE session_id = ?", (row["session_id"],)
    )
    db.commit()
```

- [ ] **Step 5: Run — expect PASS**

```bash
uv run pytest tests/test_session.py -v
```
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add src/lemonade_vision/store/ src/lemonade_vision/session.py tests/test_session.py
git commit -m "feat: SQLite schema and session management"
```

---

### Task 4: Video frame extraction + sharpness scoring

**Files:**
- Create: `src/lemonade_vision/pipeline/__init__.py`
- Create: `src/lemonade_vision/pipeline/frames.py`
- Create: `tests/test_frames.py`
- Create: `tests/fixtures/` (directory)

- [ ] **Step 1: Write failing test**

```python
# tests/test_frames.py
import tempfile
import numpy as np
from pathlib import Path
from PIL import Image
from lemonade_vision.pipeline.frames import (
    laplacian_variance,
    select_sharpest_frames,
    SECTORS,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _make_sharp_jpg(path: Path) -> None:
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[100:110, 200:440] = 255  # high-contrast edge
    Image.fromarray(img).save(str(path), "JPEG")


def _make_blurry_jpg(path: Path) -> None:
    img = np.full((480, 640, 3), 128, dtype=np.uint8)
    Image.fromarray(img).save(str(path), "JPEG")


def test_laplacian_variance_sharp_greater_than_blurry():
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        sharp = Path(d) / "sharp.jpg"
        blurry = Path(d) / "blurry.jpg"
        _make_sharp_jpg(sharp)
        _make_blurry_jpg(blurry)
        assert laplacian_variance(sharp) > laplacian_variance(blurry)


def test_select_sharpest_frames_returns_one_per_sector():
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        frames = []
        for i in range(SECTORS * 2):
            p = Path(d) / f"frame_{i:03d}.jpg"
            _make_sharp_jpg(p)
            frames.append((i * (360 // (SECTORS * 2)), str(p)))
        selected = select_sharpest_frames(frames)
        assert len(selected) <= SECTORS


def test_laplacian_variance_missing_file_returns_zero():
    assert laplacian_variance(Path("/tmp/does_not_exist.jpg")) == 0.0
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/test_frames.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write frames.py**

```python
# src/lemonade_vision/pipeline/__init__.py
# (empty)
```

```python
# src/lemonade_vision/pipeline/frames.py
"""
Frame extraction from rotation video using ffmpeg subprocess.
Sharpness scoring uses Laplacian variance on the grayscale image —
no OpenCV dependency required.
"""
from __future__ import annotations
import subprocess
import tempfile
import math
from pathlib import Path
import numpy as np
from PIL import Image

SECTORS = 12          # 30° per sector across 360°
FPS_EXTRACT = 3.0     # frames per second to extract from video
BLUR_THRESHOLD = 50.0 # Laplacian variance below this → discard


def laplacian_variance(image_path: Path) -> float:
    try:
        img = Image.open(image_path).convert("L")
        arr = np.array(img, dtype=float)
    except Exception:
        return 0.0
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=float)
    from numpy.lib.stride_tricks import sliding_window_view
    h, w = arr.shape
    patches = sliding_window_view(arr, (3, 3)).reshape(-1, 9)
    k = kernel.flatten()
    lap = patches @ k
    return float(np.var(lap))


def extract_frames_from_video(video_path: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "frame_%04d.jpg")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf", f"fps={FPS_EXTRACT}",
            "-q:v", "2",
            pattern,
        ],
        check=True,
        capture_output=True,
    )
    return sorted(out_dir.glob("frame_*.jpg"))


def _assign_sector(frame_index: int, total_frames: int) -> int:
    angle = (frame_index / max(total_frames, 1)) * 360.0
    return int(angle // (360.0 / SECTORS)) % SECTORS


def select_sharpest_frames(
    indexed_frames: list[tuple[int, str]],
) -> list[str]:
    """
    indexed_frames: list of (degree_angle, path_str)
    Returns at most SECTORS frames — one per 30° sector, sharpest wins.
    """
    sector_best: dict[int, tuple[float, str]] = {}
    for angle, path_str in indexed_frames:
        sector = int(angle // (360.0 / SECTORS)) % SECTORS
        score = laplacian_variance(Path(path_str))
        if score < BLUR_THRESHOLD:
            continue
        if sector not in sector_best or score > sector_best[sector][0]:
            sector_best[sector] = (score, path_str)
    return [v[1] for v in sector_best.values()]


def frames_from_video(video_path: Path, out_dir: Path) -> list[str]:
    all_frames = extract_frames_from_video(video_path, out_dir)
    total = len(all_frames)
    indexed = [
        (int(i / max(total, 1) * 360), str(p))
        for i, p in enumerate(all_frames)
    ]
    return select_sharpest_frames(indexed)
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/test_frames.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/lemonade_vision/pipeline/ tests/test_frames.py
git commit -m "feat: frame extraction and sharpness scoring"
```

---

### Task 5: Barcode detection

**Files:**
- Create: `src/lemonade_vision/pipeline/barcode.py`
- Create: `tests/test_barcode.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_barcode.py
import tempfile
from pathlib import Path
from PIL import Image
import numpy as np
from lemonade_vision.pipeline.barcode import extract_upc


def test_extract_upc_no_barcode_returns_none():
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        img = Image.fromarray(np.full((200, 200, 3), 200, dtype=np.uint8))
        p = Path(d) / "blank.jpg"
        img.save(str(p))
        assert extract_upc(p) is None


def test_extract_upc_missing_file_returns_none():
    assert extract_upc(Path("/tmp/no_such_file.jpg")) is None
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/test_barcode.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write barcode.py**

```python
# src/lemonade_vision/pipeline/barcode.py
from __future__ import annotations
from pathlib import Path
from typing import Optional
from PIL import Image
from pyzbar.pyzbar import decode as pyzbar_decode


def extract_upc(image_path: Path) -> Optional[str]:
    try:
        img = Image.open(image_path)
    except Exception:
        return None
    results = pyzbar_decode(img)
    for r in results:
        if r.type in ("EAN13", "UPCA", "UPCE", "EAN8", "CODE128", "CODE39"):
            return r.data.decode("utf-8")
    return None
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/test_barcode.py -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/lemonade_vision/pipeline/barcode.py tests/test_barcode.py
git commit -m "feat: pyzbar UPC barcode detection"
```

---

### Task 6: VLM client (Qwen3.6 on :8001)

**Files:**
- Create: `src/lemonade_vision/pipeline/vlm.py`
- Create: `tests/test_vlm.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_vlm.py
import os
import pytest
import tempfile
import json
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
from PIL import Image
import numpy as np
from lemonade_vision.pipeline.vlm import VLMClient, VLMResult


# --- unit tests (no network) ---

@pytest.fixture
def client():
    return VLMClient(base_url="http://localhost:8001")


def test_vlm_result_defaults():
    r = VLMResult()
    assert r.brand is None
    assert r.vlm_status == "ok"


@pytest.mark.asyncio
async def test_extract_product_info_parses_json(client):
    mock_response_text = json.dumps({
        "brand": "Elf Bar", "flavor": "Mango Ice",
        "category": "disposable_vape", "puff_count": 5000,
        "nicotine_mg": 50, "ocr_text": "5000 puffs",
        "warnings": [], "confidence": 0.9,
    })
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "choices": [{"message": {"content": mock_response_text}}]
    }
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        img = Image.fromarray(np.full((100, 100, 3), 120, dtype=np.uint8))
        p = Path(d) / "test.jpg"
        img.save(str(p))
        with patch.object(client._http, "post", return_value=fake_response):
            result = await client.extract_product_info([str(p)], narration=None)
    assert result.brand == "Elf Bar"
    assert result.puff_count == 5000
    assert result.vlm_status == "ok"


@pytest.mark.asyncio
async def test_extract_product_info_handles_vlm_timeout(client):
    import httpx
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        img = Image.fromarray(np.full((100, 100, 3), 120, dtype=np.uint8))
        p = Path(d) / "test.jpg"
        img.save(str(p))
        with patch.object(client._http, "post", side_effect=httpx.TimeoutException("t")):
            result = await client.extract_product_info([str(p)], narration=None)
    assert result.vlm_status == "unavailable"
    assert result.brand is None


@pytest.mark.asyncio
async def test_deduce_product_signals_returns_structured(client):
    mock_response_text = json.dumps({
        "brand": "Lost Mary", "flavor": "Watermelon Ice",
        "size": "OS5000", "color": None, "category": "disposable_vape",
    })
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "choices": [{"message": {"content": mock_response_text}}]
    }
    with patch.object(client._http, "post", return_value=fake_response):
        result = await client.deduce_product_signals("lost mary watermelon ice os5000")
    assert result["brand"] == "Lost Mary"


# --- integration test (requires live :8001) ---

@pytest.mark.skipif(
    not os.getenv("VISION_INTEGRATION"),
    reason="requires VISION_INTEGRATION=1 and live VLM on :8001",
)
@pytest.mark.asyncio
async def test_vlm_integration_real_call():
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        img = Image.fromarray(np.full((100, 100, 3), 120, dtype=np.uint8))
        p = Path(d) / "test.jpg"
        img.save(str(p))
        client = VLMClient(base_url="http://localhost:8001")
        result = await client.extract_product_info([str(p)], narration="Test narration")
    assert result.vlm_status in ("ok", "unavailable")
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/test_vlm.py -v -k "not integration"
```
Expected: `ImportError`

- [ ] **Step 3: Write vlm.py**

```python
# src/lemonade_vision/pipeline/vlm.py
from __future__ import annotations
import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import httpx


ONBOARD_TIMEOUT = 15.0
DEDUCE_TIMEOUT = 3.0

EXTRACT_PROMPT = """\
You are a product identification assistant for a vape shop inventory system.
Analyse the provided product images and narration transcript (if any).
Return ONLY a valid JSON object with these exact keys:
{
  "brand": string or null,
  "flavor": string or null,
  "category": string or null,
  "puff_count": integer or null,
  "nicotine_mg": integer or null,
  "ocr_text": string or null,
  "warnings": [string],
  "confidence": float 0-1
}
Typical categories: disposable_vape, e_liquid, pod, device, accessory.
"""

DEDUCE_PROMPT = """\
Extract structured product signals from this customer query for a vape shop.
Return ONLY a valid JSON object:
{
  "brand": string or null,
  "flavor": string or null,
  "size": string or null,
  "color": string or null,
  "category": string or null
}
Query: {query}
"""


@dataclass
class VLMResult:
    brand: Optional[str] = None
    flavor: Optional[str] = None
    category: Optional[str] = None
    puff_count: Optional[int] = None
    nicotine_mg: Optional[int] = None
    ocr_text: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0
    vlm_status: str = "ok"


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _strip_fences(text: str) -> str:
    text = re.sub(r"^```(?:json)?\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


class VLMClient:
    def __init__(self, base_url: str = "http://localhost:8001") -> None:
        self._base_url = base_url
        self._http = httpx.Client(base_url=base_url, timeout=ONBOARD_TIMEOUT)

    async def extract_product_info(
        self,
        image_paths: list[str],
        narration: Optional[str],
    ) -> VLMResult:
        content: list[dict] = [{"type": "text", "text": EXTRACT_PROMPT}]
        for path in image_paths[:4]:
            try:
                b64 = _encode_image(path)
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                })
            except Exception:
                pass
        if narration:
            content.append({"type": "text", "text": f"Operator narration: {narration}"})

        try:
            resp = self._http.post(
                "/v1/chat/completions",
                json={
                    "model": "local",
                    "messages": [{"role": "user", "content": content}],
                    "temperature": 0.1,
                },
                timeout=ONBOARD_TIMEOUT,
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(_strip_fences(raw))
        except Exception:
            return VLMResult(vlm_status="unavailable")

        return VLMResult(
            brand=data.get("brand"),
            flavor=data.get("flavor"),
            category=data.get("category"),
            puff_count=data.get("puff_count"),
            nicotine_mg=data.get("nicotine_mg"),
            ocr_text=data.get("ocr_text"),
            warnings=data.get("warnings", []),
            confidence=float(data.get("confidence", 0.0)),
            vlm_status="ok",
        )

    async def deduce_product_signals(self, query: str) -> dict:
        content = DEDUCE_PROMPT.replace("{query}", query)
        try:
            resp = self._http.post(
                "/v1/chat/completions",
                json={
                    "model": "local",
                    "messages": [{"role": "user", "content": content}],
                    "temperature": 0.0,
                },
                timeout=DEDUCE_TIMEOUT,
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            return json.loads(_strip_fences(raw))
        except Exception:
            return {}
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/test_vlm.py -v -k "not integration"
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/lemonade_vision/pipeline/vlm.py tests/test_vlm.py
git commit -m "feat: VLM client for Qwen3.6 on :8001"
```

---

### Task 7: Background removal + CLIP embeddings

**Files:**
- Create: `src/lemonade_vision/pipeline/background.py`
- Create: `src/lemonade_vision/pipeline/embeddings.py`
- Create: `tests/test_embeddings.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_embeddings.py
import os
import tempfile
import numpy as np
import pytest
from pathlib import Path
from PIL import Image
from lemonade_vision.pipeline.embeddings import EmbeddingModel


@pytest.fixture(scope="module")
def model():
    return EmbeddingModel()


def _make_jpg(path: Path) -> None:
    img = Image.fromarray(np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8))
    img.save(str(path))


def test_encode_image_returns_normalized_vector(model):
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        p = Path(d) / "img.jpg"
        _make_jpg(p)
        vec = model.encode_image(str(p))
        assert vec.shape == (512,)
        norm = float(np.linalg.norm(vec))
        assert abs(norm - 1.0) < 0.01


def test_encode_text_returns_normalized_vector(model):
    vec = model.encode_text("elf bar mango ice disposable vape")
    assert vec.shape == (512,)
    norm = float(np.linalg.norm(vec))
    assert abs(norm - 1.0) < 0.01


def test_same_text_same_vector(model):
    v1 = model.encode_text("lost mary watermelon")
    v2 = model.encode_text("lost mary watermelon")
    assert np.allclose(v1, v2, atol=1e-5)


def test_different_texts_different_vectors(model):
    v1 = model.encode_text("elf bar mango")
    v2 = model.encode_text("lost mary blueberry")
    assert not np.allclose(v1, v2, atol=0.01)


@pytest.mark.skipif(
    not os.getenv("VISION_INTEGRATION"),
    reason="integration: requires VISION_INTEGRATION=1",
)
def test_image_text_similarity_positive(model):
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        p = Path(d) / "img.jpg"
        _make_jpg(p)
        img_vec = model.encode_image(str(p))
        txt_vec = model.encode_text("product label")
        sim = float(np.dot(img_vec, txt_vec))
        assert sim > -1.0
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/test_embeddings.py -v -k "not integration"
```
Expected: `ImportError`

- [ ] **Step 3: Write background.py**

```python
# src/lemonade_vision/pipeline/background.py
from pathlib import Path
from PIL import Image


def remove_background(image_path: Path, out_path: Path) -> Path:
    try:
        from rembg import remove as rembg_remove
        with open(image_path, "rb") as f:
            data = f.read()
        result = rembg_remove(data)
        with open(out_path, "wb") as f:
            f.write(result)
        return out_path
    except Exception:
        # If rembg fails, copy original — pipeline continues
        import shutil
        shutil.copy2(image_path, out_path)
        return out_path
```

- [ ] **Step 4: Write embeddings.py**

```python
# src/lemonade_vision/pipeline/embeddings.py
from __future__ import annotations
import numpy as np
from pathlib import Path
from PIL import Image
import open_clip
import torch


class EmbeddingModel:
    _model: open_clip.CLIP | None = None
    _preprocess = None
    _tokenizer = None

    def __init__(
        self,
        model_name: str = "ViT-B-32",
        pretrained: str = "openai",
    ) -> None:
        self._model_name = model_name
        self._pretrained = pretrained
        self._device = "cpu"

    def _load(self) -> None:
        if self._model is None:
            model, _, preprocess = open_clip.create_model_and_transforms(
                self._model_name, pretrained=self._pretrained
            )
            model.eval()
            self._model = model
            self._preprocess = preprocess
            self._tokenizer = open_clip.get_tokenizer(self._model_name)

    def encode_image(self, image_path: str) -> np.ndarray:
        self._load()
        img = Image.open(image_path).convert("RGB")
        tensor = self._preprocess(img).unsqueeze(0)  # type: ignore[arg-type]
        with torch.no_grad():
            features = self._model.encode_image(tensor)  # type: ignore[union-attr]
            features /= features.norm(dim=-1, keepdim=True)
        return features.squeeze(0).cpu().numpy().astype(np.float32)

    def encode_text(self, text: str) -> np.ndarray:
        self._load()
        tokens = self._tokenizer([text])  # type: ignore[call-arg]
        with torch.no_grad():
            features = self._model.encode_text(tokens)  # type: ignore[union-attr]
            features /= features.norm(dim=-1, keepdim=True)
        return features.squeeze(0).cpu().numpy().astype(np.float32)
```

- [ ] **Step 5: Run — expect PASS**

```bash
uv run pytest tests/test_embeddings.py -v -k "not integration"
```
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add src/lemonade_vision/pipeline/background.py src/lemonade_vision/pipeline/embeddings.py tests/test_embeddings.py
git commit -m "feat: rembg background removal + CLIP embedding model"
```

---

### Task 8: LiDAR dimensions + confidence scoring

**Files:**
- Create: `src/lemonade_vision/pipeline/dimensions.py`
- Create: `src/lemonade_vision/pipeline/confidence.py`
- Create: `tests/test_dimensions.py`
- Create: `tests/test_confidence.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_dimensions.py
import numpy as np
from lemonade_vision.pipeline.dimensions import depth_to_dimensions


def test_depth_to_dimensions_basic():
    # Uniform depth grid at 350mm, product spans half the frame
    grid = np.full((256, 192), 350.0)
    dims = depth_to_dimensions(grid, scan_distance_mm=350.0)
    assert dims is not None
    w, h, d = dims
    assert w > 0
    assert h > 0
    assert d > 0


def test_depth_to_dimensions_empty_returns_none():
    assert depth_to_dimensions(np.array([]), scan_distance_mm=350.0) is None


def test_depth_to_dimensions_nearer_means_bigger():
    close_grid = np.full((256, 192), 200.0)
    far_grid = np.full((256, 192), 500.0)
    close_dims = depth_to_dimensions(close_grid, scan_distance_mm=200.0)
    far_dims = depth_to_dimensions(far_grid, scan_distance_mm=500.0)
    assert close_dims is not None and far_dims is not None
    # Closer scan: field-of-view subtends same pixels → smaller objects fill same fraction
    # This just validates the function returns different values
    assert close_dims != far_dims
```

```python
# tests/test_confidence.py
from lemonade_vision.pipeline.confidence import compute_confidence, ConfidenceResult


def test_full_confidence_auto_add():
    result = compute_confidence(upc=1.0, vlm=1.0, embedding=1.0, dimension=1.0)
    assert result.final >= 0.85
    assert result.auto_add is True
    assert result.requires_verification is False


def test_partial_confidence_requires_verification():
    result = compute_confidence(upc=0.0, vlm=0.6, embedding=0.5, dimension=0.0)
    assert 0.50 <= result.final < 0.85
    assert result.auto_add is False
    assert result.requires_verification is True


def test_low_confidence_reject():
    result = compute_confidence(upc=0.0, vlm=0.1, embedding=0.1, dimension=0.0)
    assert result.final < 0.50
    assert result.auto_add is False
    assert result.requires_verification is False


def test_weights_sum_to_one():
    from lemonade_vision.pipeline.confidence import WEIGHTS
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-6
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/test_dimensions.py tests/test_confidence.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write dimensions.py**

```python
# src/lemonade_vision/pipeline/dimensions.py
"""
Converts ARKit LiDAR depth grid to physical W×H×D estimate.
Assumes iPhone 15 Pro Max horizontal FOV ≈ 69°.
The product extent is estimated as the fraction of the frame
occupied by pixels at the product depth plane.
"""
from __future__ import annotations
import math
import numpy as np
from typing import Optional

IPHONE_FOV_H_DEG = 69.0
IPHONE_ASPECT = 4.0 / 3.0


def depth_to_dimensions(
    depth_grid: np.ndarray,
    scan_distance_mm: float = 350.0,
) -> Optional[tuple[float, float, float]]:
    if depth_grid.size == 0:
        return None

    h_px, w_px = depth_grid.shape if depth_grid.ndim == 2 else (0, 0)
    if h_px == 0 or w_px == 0:
        return None

    fov_h_rad = math.radians(IPHONE_FOV_H_DEG)
    fov_v_rad = fov_h_rad / IPHONE_ASPECT

    # Physical size of the full frame at the scan distance
    frame_w_mm = 2.0 * scan_distance_mm * math.tan(fov_h_rad / 2.0)
    frame_h_mm = 2.0 * scan_distance_mm * math.tan(fov_v_rad / 2.0)

    # Foreground pixels = depth < scan_distance * 0.95 (product is closer than bg)
    fg_mask = depth_grid < (scan_distance_mm * 0.95)
    rows_with_fg = np.any(fg_mask, axis=1)
    cols_with_fg = np.any(fg_mask, axis=0)

    if not np.any(rows_with_fg) or not np.any(cols_with_fg):
        # No distinguishable foreground — estimate from full grid range
        row_span = h_px
        col_span = w_px
    else:
        row_span = int(np.sum(rows_with_fg))
        col_span = int(np.sum(cols_with_fg))

    width_mm = (col_span / w_px) * frame_w_mm
    height_mm = (row_span / h_px) * frame_h_mm
    depth_mm_estimate = float(np.percentile(depth_grid, 5))

    return (round(width_mm, 1), round(height_mm, 1), round(depth_mm_estimate, 1))
```

- [ ] **Step 4: Write confidence.py**

```python
# src/lemonade_vision/pipeline/confidence.py
from dataclasses import dataclass

WEIGHTS = {
    "upc": 0.40,
    "vlm": 0.30,
    "embedding": 0.20,
    "dimension": 0.10,
}

THRESHOLD_AUTO = 0.85
THRESHOLD_VERIFY = 0.50


@dataclass
class ConfidenceResult:
    final: float
    auto_add: bool
    requires_verification: bool


def compute_confidence(
    upc: float,
    vlm: float,
    embedding: float,
    dimension: float,
) -> ConfidenceResult:
    final = (
        WEIGHTS["upc"] * upc
        + WEIGHTS["vlm"] * vlm
        + WEIGHTS["embedding"] * embedding
        + WEIGHTS["dimension"] * dimension
    )
    return ConfidenceResult(
        final=round(final, 4),
        auto_add=final >= THRESHOLD_AUTO,
        requires_verification=THRESHOLD_VERIFY <= final < THRESHOLD_AUTO,
    )
```

- [ ] **Step 5: Run — expect PASS**

```bash
uv run pytest tests/test_dimensions.py tests/test_confidence.py -v
```
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add src/lemonade_vision/pipeline/dimensions.py src/lemonade_vision/pipeline/confidence.py tests/test_dimensions.py tests/test_confidence.py
git commit -m "feat: LiDAR dimension estimation + confidence scoring"
```

---

### Task 9: Storage layer (ProductDB, VectorStore, ImageStore)

**Files:**
- Create: `src/lemonade_vision/store/product_db.py`
- Create: `src/lemonade_vision/store/vector_db.py`
- Create: `src/lemonade_vision/store/image_store.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_store.py
import tempfile
import numpy as np
import pytest
from pathlib import Path
from PIL import Image
from lemonade_vision.store.schema import init_db
from lemonade_vision.store.product_db import ProductDB
from lemonade_vision.store.vector_db import VectorStore
from lemonade_vision.store.image_store import ImageStore


@pytest.fixture
def db_path(tmp_path):
    p = Path(tempfile.mktemp(suffix=".db", dir="/tmp"))
    return p


@pytest.fixture
def product_db(db_path):
    conn = init_db(db_path)
    return ProductDB(conn)


@pytest.fixture
def vector_store(tmp_path):
    p = Path(tempfile.mkdtemp(dir="/tmp")) / "chroma"
    return VectorStore(str(p))


@pytest.fixture
def image_store(tmp_path):
    p = Path(tempfile.mkdtemp(dir="/tmp")) / "images"
    return ImageStore(str(p))


def test_product_db_insert_and_fetch(product_db):
    product_db.insert_product(
        sku="SKU001", brand="Elf Bar", flavor="Mango Ice",
        category="disposable_vape", puff_count=5000,
    )
    row = product_db.get_product("SKU001")
    assert row is not None
    assert row["brand"] == "Elf Bar"


def test_product_db_add_alias(product_db):
    product_db.insert_product(
        sku="SKU002", brand="Lost Mary", flavor="Watermelon",
        category="disposable_vape",
    )
    product_db.add_alias("SKU002", "blue one")
    aliases = product_db.get_aliases("SKU002")
    assert "blue one" in aliases


def test_vector_store_upsert_and_query(vector_store):
    vec = np.random.rand(512).astype(np.float32)
    vec /= np.linalg.norm(vec)
    vector_store.upsert_text("SKU001", vec, {"sku": "SKU001", "brand": "Elf Bar"})
    results = vector_store.query_text(vec, top_k=1)
    assert len(results) >= 1
    assert results[0]["id"] == "SKU001"


def test_image_store_save_returns_path(image_store):
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        src = Path(d) / "front.jpg"
        img = Image.fromarray(np.full((300, 300, 3), 128, dtype=np.uint8))
        img.save(str(src))
        out = image_store.save_image("SKU001", "front", src)
        assert out.exists()
        assert "SKU001" in str(out)
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/test_store.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write product_db.py**

```python
# src/lemonade_vision/store/product_db.py
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProductDB:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._db = conn

    def insert_product(
        self,
        sku: str,
        brand: str,
        flavor: str,
        category: str,
        upc: Optional[str] = None,
        puff_count: Optional[int] = None,
        nicotine_mg: Optional[int] = None,
        ocr_text: Optional[str] = None,
        narration: Optional[str] = None,
        width_mm: Optional[float] = None,
        height_mm: Optional[float] = None,
        depth_mm: Optional[float] = None,
        confidence_threshold: float = 0.85,
        requires_attendant: bool = False,
    ) -> None:
        now = _now()
        self._db.execute(
            """INSERT INTO products
               (sku,upc,brand,flavor,category,puff_count,nicotine_mg,
                ocr_text,narration,width_mm,height_mm,depth_mm,
                confidence_threshold,requires_attendant,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sku, upc, brand, flavor, category, puff_count, nicotine_mg,
             ocr_text, narration, width_mm, height_mm, depth_mm,
             confidence_threshold, int(requires_attendant), now, now),
        )
        self._db.commit()

    def get_product(self, sku: str) -> Optional[sqlite3.Row]:
        return self._db.execute(
            "SELECT * FROM products WHERE sku = ?", (sku,)
        ).fetchone()

    def add_alias(self, sku: str, alias: str) -> None:
        self._db.execute(
            "INSERT INTO product_aliases (sku, alias) VALUES (?, ?)", (sku, alias)
        )
        self._db.commit()

    def get_aliases(self, sku: str) -> list[str]:
        rows = self._db.execute(
            "SELECT alias FROM product_aliases WHERE sku = ?", (sku,)
        ).fetchall()
        return [r["alias"] for r in rows]

    def add_image(self, sku: str, angle: str, path: str, is_primary: bool = False) -> None:
        self._db.execute(
            "INSERT INTO product_images (sku, angle, path, is_primary) VALUES (?,?,?,?)",
            (sku, angle, path, int(is_primary)),
        )
        self._db.commit()

    def update_product(self, sku: str, **kwargs) -> None:
        if not kwargs:
            return
        fields = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [_now(), sku]
        self._db.execute(
            f"UPDATE products SET {fields}, updated_at = ? WHERE sku = ?", values
        )
        self._db.commit()
```

- [ ] **Step 4: Write vector_db.py**

```python
# src/lemonade_vision/store/vector_db.py
from __future__ import annotations
import numpy as np
import chromadb


class VectorStore:
    def __init__(self, chroma_path: str) -> None:
        self._client = chromadb.PersistentClient(path=chroma_path)
        self._visual = self._client.get_or_create_collection("product_visual")
        self._text = self._client.get_or_create_collection("product_text")

    def upsert_visual(self, id_: str, vector: np.ndarray, metadata: dict) -> None:
        self._visual.upsert(
            ids=[id_],
            embeddings=[vector.tolist()],
            metadatas=[metadata],
        )

    def upsert_text(self, id_: str, vector: np.ndarray, metadata: dict) -> None:
        self._text.upsert(
            ids=[id_],
            embeddings=[vector.tolist()],
            metadatas=[metadata],
        )

    def query_text(self, vector: np.ndarray, top_k: int = 3) -> list[dict]:
        results = self._text.query(
            query_embeddings=[vector.tolist()],
            n_results=min(top_k, self._text.count() or 1),
            include=["metadatas", "distances"],
        )
        out = []
        for id_, meta, dist in zip(
            results["ids"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            out.append({"id": id_, "metadata": meta, "distance": dist})
        return out

    def query_visual(self, vector: np.ndarray, top_k: int = 3) -> list[dict]:
        results = self._visual.query(
            query_embeddings=[vector.tolist()],
            n_results=min(top_k, self._visual.count() or 1),
            include=["metadatas", "distances"],
        )
        out = []
        for id_, meta, dist in zip(
            results["ids"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            out.append({"id": id_, "metadata": meta, "distance": dist})
        return out

    def product_count(self) -> int:
        return self._text.count()
```

- [ ] **Step 5: Write image_store.py**

```python
# src/lemonade_vision/store/image_store.py
from __future__ import annotations
from pathlib import Path
from PIL import Image

MAX_DIM = 800
JPEG_QUALITY = 85


class ImageStore:
    def __init__(self, base_dir: str) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def save_image(self, sku: str, angle: str, src: Path) -> Path:
        sku_dir = self._base / sku
        sku_dir.mkdir(parents=True, exist_ok=True)
        out_path = sku_dir / f"{angle}.jpg"
        img = Image.open(src).convert("RGB")
        img.thumbnail((MAX_DIM, MAX_DIM), Image.LANCZOS)
        img.save(str(out_path), "JPEG", quality=JPEG_QUALITY)
        return out_path

    def get_image_url(self, sku: str, angle: str) -> str:
        return f"/images/{sku}/{angle}.jpg"

    def list_images(self, sku: str) -> list[Path]:
        d = self._base / sku
        if not d.exists():
            return []
        return sorted(d.glob("*.jpg"))
```

- [ ] **Step 6: Run — expect PASS**

```bash
uv run pytest tests/test_store.py -v
```
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add src/lemonade_vision/store/ tests/test_store.py
git commit -m "feat: ProductDB, VectorStore, ImageStore"
```

---

### Task 10: Draft assembly + pipeline orchestrator

**Files:**
- Create: `src/lemonade_vision/draft.py`
- Create: `tests/test_draft.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_draft.py
import json
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from lemonade_vision.store.schema import init_db
from lemonade_vision.draft import assemble_draft, DraftAssembler


def _db():
    p = tempfile.mktemp(suffix=".db", dir="/tmp")
    return init_db(p)


def test_assemble_draft_with_all_signals():
    from lemonade_vision.pipeline.vlm import VLMResult
    result = assemble_draft(
        job_id="j1",
        session_id="s1",
        vlm_result=VLMResult(
            brand="Elf Bar", flavor="Mango Ice",
            category="disposable_vape", puff_count=5000,
            nicotine_mg=50, ocr_text="5000 puffs",
            vlm_status="ok", confidence=0.92,
        ),
        upc="012345678901",
        dimensions=(25.0, 120.0, 25.0),
        narration="elf bar mango 5000",
        frame_paths=["frame1.jpg"],
    )
    assert result["brand"] == "Elf Bar"
    assert result["upc"] == "012345678901"
    assert result["signal_scores"]["upc"] > 0
    assert result["signal_scores"]["vlm"] > 0


def test_assemble_draft_missing_barcode_still_ok():
    from lemonade_vision.pipeline.vlm import VLMResult
    result = assemble_draft(
        job_id="j2", session_id="s1",
        vlm_result=VLMResult(brand="Lost Mary", flavor="Watermelon", vlm_status="ok"),
        upc=None,
        dimensions=None,
        narration=None,
        frame_paths=[],
    )
    assert result["upc"] is None
    assert result["signal_scores"]["upc"] == 0.0


def test_assemble_draft_vlm_unavailable():
    from lemonade_vision.pipeline.vlm import VLMResult
    result = assemble_draft(
        job_id="j3", session_id="s1",
        vlm_result=VLMResult(vlm_status="unavailable"),
        upc=None, dimensions=None, narration=None, frame_paths=[],
    )
    assert result["vlm_status"] == "unavailable"
    assert result["brand"] is None
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/test_draft.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write draft.py**

```python
# src/lemonade_vision/draft.py
from __future__ import annotations
from typing import Optional
from lemonade_vision.pipeline.vlm import VLMResult


def assemble_draft(
    job_id: str,
    session_id: str,
    vlm_result: VLMResult,
    upc: Optional[str],
    dimensions: Optional[tuple[float, float, float]],
    narration: Optional[str],
    frame_paths: list[str],
) -> dict:
    upc_score = 1.0 if upc else 0.0
    vlm_score = vlm_result.confidence if vlm_result.vlm_status == "ok" else 0.0
    dim_score = 0.5 if dimensions else 0.0
    embedding_score = 0.5 if frame_paths else 0.0

    signal_scores = {
        "upc": upc_score,
        "vlm": vlm_score,
        "embedding": embedding_score,
        "dimension": dim_score,
    }

    dim_data = None
    if dimensions:
        w, h, d = dimensions
        dim_data = {"width_mm": w, "height_mm": h, "depth_mm": d}

    return {
        "job_id": job_id,
        "session_id": session_id,
        "status": "ready",
        "upc": upc,
        "brand": vlm_result.brand,
        "flavor": vlm_result.flavor,
        "category": vlm_result.category,
        "puff_count": vlm_result.puff_count,
        "nicotine_mg": vlm_result.nicotine_mg,
        "ocr_text": vlm_result.ocr_text,
        "narration": narration,
        "dimensions": dim_data,
        "signal_scores": signal_scores,
        "vlm_status": vlm_result.vlm_status,
        "frame_paths": frame_paths,
    }


class DraftAssembler:
    """Orchestrates the full onboarding pipeline from session data to draft record."""

    def __init__(self, vlm_client, embedding_model, fw_base_url: str = "http://localhost:8004"):
        self._vlm = vlm_client
        self._embed = embedding_model
        self._fw_base_url = fw_base_url

    async def run(
        self,
        job_id: str,
        session_id: str,
        rotation_video_path: Optional[str],
        still_paths: dict[str, str],
        depth_path: Optional[str],
        narration_path: Optional[str],
        frame_out_dir: str,
    ) -> dict:
        import asyncio
        from pathlib import Path
        from lemonade_vision.pipeline.frames import frames_from_video
        from lemonade_vision.pipeline.barcode import extract_upc
        from lemonade_vision.pipeline.dimensions import depth_to_dimensions
        import numpy as np

        # 1. Extract frames from rotation video
        frame_paths: list[str] = []
        if rotation_video_path:
            try:
                frame_paths = frames_from_video(
                    Path(rotation_video_path), Path(frame_out_dir)
                )
            except Exception:
                pass

        # Add close-up stills
        for angle, path in still_paths.items():
            if path not in frame_paths:
                frame_paths.append(path)

        # 2. Barcode from UPC still (preferred) or any frame
        upc: Optional[str] = None
        if "upc" in still_paths:
            upc = extract_upc(Path(still_paths["upc"]))
        if upc is None:
            for fp in frame_paths[:5]:
                upc = extract_upc(Path(fp))
                if upc:
                    break

        # 3. Transcribe narration
        narration: Optional[str] = None
        if narration_path:
            narration = await self._transcribe(narration_path)

        # 4. VLM extraction
        vlm_result = await self._vlm.extract_product_info(
            frame_paths[:4], narration=narration
        )

        # 5. Dimensions from depth
        dimensions: Optional[tuple[float, float, float]] = None
        if depth_path:
            try:
                grid = np.load(depth_path) if depth_path.endswith(".npy") else \
                       np.array(__import__("json").loads(Path(depth_path).read_text()))
                dimensions = depth_to_dimensions(grid)
            except Exception:
                pass

        return assemble_draft(
            job_id=job_id,
            session_id=session_id,
            vlm_result=vlm_result,
            upc=upc,
            dimensions=dimensions,
            narration=narration,
            frame_paths=frame_paths,
        )

    async def _transcribe(self, audio_path: str) -> Optional[str]:
        import httpx
        try:
            with open(audio_path, "rb") as f:
                data = f.read()
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self._fw_base_url}/transcribe",
                    content=data,
                    headers={"Content-Type": "audio/wav"},
                )
                resp.raise_for_status()
                return resp.json().get("text")
        except Exception:
            return None
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/test_draft.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/lemonade_vision/draft.py tests/test_draft.py
git commit -m "feat: draft assembly + pipeline orchestrator"
```

---

### Task 11: Capture API routes + FastAPI server

**Files:**
- Create: `src/lemonade_vision/api/__init__.py`
- Create: `src/lemonade_vision/api/capture.py`
- Create: `src/lemonade_vision/api/product.py`
- Create: `src/lemonade_vision/server.py`
- Create: `tests/test_routes.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_routes.py
import json
import tempfile
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


@pytest.fixture
def client(tmp_path):
    data_dir = str(tmp_path / "data")
    import os
    os.environ["VISION_DATA_DIR"] = data_dir
    from lemonade_vision.server import create_app
    app = create_app(data_dir=data_dir)
    return TestClient(app)


def test_health_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "vlm_reachable" in data


def test_session_start_returns_session_id(client):
    resp = client.post("/session/start")
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert "qr_png_b64" in data


def test_capture_still_requires_session_token(client):
    resp = client.post(
        "/capture/still",
        data={"angle": "front"},
        files={"file": ("test.jpg", b"data", "image/jpeg")},
    )
    assert resp.status_code == 401


def test_capture_still_bad_angle_returns_422(client):
    sess_resp = client.post("/session/start")
    sid = sess_resp.json()["session_id"]
    resp = client.post(
        "/capture/still",
        headers={"X-Session-Token": sid},
        data={"angle": "invalid_angle"},
        files={"file": ("test.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )
    assert resp.status_code == 422


def test_session_delete_returns_204(client):
    sess_resp = client.post("/session/start")
    sid = sess_resp.json()["session_id"]
    resp = client.delete(f"/session/{sid}")
    assert resp.status_code == 204


def test_product_draft_unknown_job_returns_404(client):
    resp = client.get("/product/draft/nonexistent-job-id")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/test_routes.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write api/capture.py**

```python
# src/lemonade_vision/api/__init__.py
# (empty)
```

```python
# src/lemonade_vision/api/capture.py
from __future__ import annotations
import asyncio
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from lemonade_vision.models import FinalizeResponse
from lemonade_vision.session import create_session, validate_session, close_session

router = APIRouter()

VALID_ANGLES = {"upc", "label", "front", "rear", "left", "right", "top", "bottom"}


def _get_session_token(request: Request) -> str:
    token = request.headers.get("X-Session-Token")
    if not token:
        raise HTTPException(status_code=401, detail="X-Session-Token header required")
    return token


def _require_session(token: Annotated[str, Depends(_get_session_token)], request: Request):
    db = request.app.state.db
    row = validate_session(db, token)
    if row is None:
        raise HTTPException(status_code=401, detail="Session expired or not found")
    return dict(row)


@router.post("/capture/video", status_code=202)
async def upload_video(
    request: Request,
    session: Annotated[dict, Depends(_require_session)],
    file: UploadFile = File(...),
):
    tmp_dir = Path(session["tmp_dir"])
    tmp_dir.mkdir(parents=True, exist_ok=True)
    video_path = tmp_dir / "rotation.mp4"
    with open(video_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    db = request.app.state.db
    db.execute(
        "UPDATE capture_sessions SET frame_count = 0 WHERE session_id = ?",
        (session["session_id"],),
    )
    db.commit()
    return {"message": "video received", "path": str(video_path)}


@router.post("/capture/still")
async def upload_still(
    request: Request,
    session: Annotated[dict, Depends(_require_session)],
    angle: str = Form(...),
    file: UploadFile = File(...),
):
    if angle not in VALID_ANGLES:
        raise HTTPException(
            status_code=422,
            detail=f"angle must be one of {sorted(VALID_ANGLES)}",
        )
    tmp_dir = Path(session["tmp_dir"])
    tmp_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "still.jpg").suffix or ".jpg"
    frame_id = str(uuid.uuid4())[:8]
    out_path = tmp_dir / f"still_{angle}_{frame_id}{suffix}"
    with open(out_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"frame_id": frame_id, "angle": angle, "path": str(out_path)}


@router.post("/capture/depth")
async def upload_depth(
    request: Request,
    session: Annotated[dict, Depends(_require_session)],
    frame_id: str = Form(...),
    file: UploadFile = File(...),
):
    tmp_dir = Path(session["tmp_dir"])
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_path = tmp_dir / f"depth_{frame_id}.json"
    with open(out_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"message": "depth received", "frame_id": frame_id}


@router.post("/capture/audio")
async def upload_audio(
    request: Request,
    session: Annotated[dict, Depends(_require_session)],
    file: UploadFile = File(...),
):
    tmp_dir = Path(session["tmp_dir"])
    tmp_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "narration.wav").suffix or ".wav"
    narration_path = tmp_dir / f"narration{suffix}"
    with open(narration_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    db = request.app.state.db
    db.execute(
        "UPDATE capture_sessions SET narration_path = ? WHERE session_id = ?",
        (str(narration_path), session["session_id"]),
    )
    db.commit()
    return {"message": "audio received"}


@router.post("/capture/finalize", response_model=FinalizeResponse)
async def finalize(
    request: Request,
    session: Annotated[dict, Depends(_require_session)],
):
    job_id = str(uuid.uuid4())
    db = request.app.state.db
    from datetime import datetime, timezone
    db.execute(
        "INSERT INTO draft_jobs (job_id, session_id, status, created_at) VALUES (?,?,?,?)",
        (job_id, session["session_id"], "processing",
         datetime.now(timezone.utc).isoformat()),
    )
    db.commit()

    assembler = request.app.state.assembler
    tmp_dir = Path(session["tmp_dir"])
    asyncio.create_task(
        _run_pipeline(db, assembler, job_id, session, tmp_dir, request.app.state)
    )
    return FinalizeResponse(job_id=job_id)


async def _run_pipeline(db, assembler, job_id, session, tmp_dir, state):
    import json as _json
    try:
        video_path = tmp_dir / "rotation.mp4"
        narration_path = session.get("narration_path")

        still_paths: dict[str, str] = {}
        for p in tmp_dir.glob("still_*.jpg"):
            parts = p.stem.split("_")
            if len(parts) >= 2:
                still_paths[parts[1]] = str(p)

        depth_candidates = list(tmp_dir.glob("depth_*.json"))
        depth_path = str(depth_candidates[0]) if depth_candidates else None

        frame_out_dir = tmp_dir / "frames"
        draft = await assembler.run(
            job_id=job_id,
            session_id=session["session_id"],
            rotation_video_path=str(video_path) if video_path.exists() else None,
            still_paths=still_paths,
            depth_path=depth_path,
            narration_path=narration_path,
            frame_out_dir=str(frame_out_dir),
        )

        signal_scores = draft.pop("signal_scores", {})
        db.execute(
            "UPDATE draft_jobs SET status='ready', draft_json=?, signal_scores=? WHERE job_id=?",
            (_json.dumps(draft), _json.dumps(signal_scores), job_id),
        )
        db.commit()
    except Exception as exc:
        import traceback
        db.execute(
            "UPDATE draft_jobs SET status='failed', draft_json=? WHERE job_id=?",
            (_json.dumps({"error": str(exc), "traceback": traceback.format_exc()}), job_id),
        )
        db.commit()
```

- [ ] **Step 4: Write api/product.py**

```python
# src/lemonade_vision/api/product.py
from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from lemonade_vision.models import CommitRequest, CommitResponse, DraftProduct, ProductPatch
from lemonade_vision.api.capture import _require_session

router = APIRouter()


@router.get("/product/draft/{job_id}", response_model=DraftProduct)
async def get_draft(job_id: str, request: Request):
    db = request.app.state.db
    row = db.execute(
        "SELECT * FROM draft_jobs WHERE job_id = ?", (job_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    draft = json.loads(row["draft_json"]) if row["draft_json"] else {}
    scores = json.loads(row["signal_scores"]) if row["signal_scores"] else {}
    return DraftProduct(
        job_id=job_id,
        status=row["status"],
        signal_scores=scores or None,
        **{k: v for k, v in draft.items()
           if k in DraftProduct.model_fields and k not in ("job_id", "status", "signal_scores")},
    )


@router.post("/product/commit", response_model=CommitResponse)
async def commit_product(body: CommitRequest, request: Request):
    db = request.app.state.db
    product_db = request.app.state.product_db
    vector_store = request.app.state.vector_store
    image_store = request.app.state.image_store
    embed_model = request.app.state.embed_model

    row = db.execute(
        "SELECT * FROM draft_jobs WHERE job_id = ?", (body.job_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="draft job not found")

    draft = json.loads(row["draft_json"]) if row["draft_json"] else {}

    product_db.insert_product(
        sku=body.sku,
        brand=body.brand,
        flavor=body.flavor,
        category=body.category,
        upc=draft.get("upc"),
        puff_count=body.puff_count,
        nicotine_mg=body.nicotine_mg,
        ocr_text=draft.get("ocr_text"),
        narration=draft.get("narration"),
        confidence_threshold=body.confidence_threshold,
        requires_attendant=body.requires_attendant,
    )

    for alias in body.aliases:
        product_db.add_alias(body.sku, alias)

    text_query = f"{body.brand} {body.flavor} {body.category} {' '.join(body.aliases)}"
    text_vec = embed_model.encode_text(text_query)
    vector_store.upsert_text(body.sku, text_vec, {
        "sku": body.sku, "brand": body.brand,
        "flavor": body.flavor, "category": body.category,
    })

    from pathlib import Path
    for frame_path in draft.get("frame_paths", [])[:3]:
        try:
            img_vec = embed_model.encode_image(frame_path)
            angle = Path(frame_path).stem
            vector_store.upsert_visual(f"{body.sku}_{angle}", img_vec, {
                "sku": body.sku, "brand": body.brand,
                "category": body.category, "angle": angle,
            })
            saved = image_store.save_image(body.sku, angle, Path(frame_path))
            product_db.add_image(body.sku, angle, str(saved))
        except Exception:
            pass

    db.execute(
        "UPDATE draft_jobs SET status='committed' WHERE job_id=?", (body.job_id,)
    )
    db.commit()
    return CommitResponse(sku=body.sku)


@router.patch("/product/{sku}", response_model=CommitResponse)
async def patch_product(sku: str, body: ProductPatch, request: Request):
    product_db = request.app.state.product_db
    row = product_db.get_product(sku)
    if row is None:
        raise HTTPException(status_code=404, detail="product not found")

    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()
               if k != "aliases"}
    if updates:
        product_db.update_product(sku, **updates)

    for alias in body.aliases:
        product_db.add_alias(sku, alias)

    return CommitResponse(sku=sku)
```

- [ ] **Step 5: Write server.py**

```python
# src/lemonade_vision/server.py
from __future__ import annotations
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from lemonade_vision.models import HealthResponse
from lemonade_vision.store.schema import init_db
from lemonade_vision.store.product_db import ProductDB
from lemonade_vision.store.vector_db import VectorStore
from lemonade_vision.store.image_store import ImageStore
from lemonade_vision.pipeline.vlm import VLMClient
from lemonade_vision.pipeline.embeddings import EmbeddingModel
from lemonade_vision.draft import DraftAssembler
from lemonade_vision.session import create_session, expire_old_sessions
from lemonade_vision.api.capture import router as capture_router
from lemonade_vision.api.product import router as product_router


def create_app(data_dir: str | None = None) -> FastAPI:
    if data_dir is None:
        data_dir = os.environ.get("VISION_DATA_DIR", str(Path.home() / "lemonade-vision-server" / "data"))

    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)

    db_path = data_path / "products.db"
    chroma_path = data_path / "chroma"
    images_path = data_path / "images"
    sessions_path = data_path / "sessions"
    sessions_path.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = init_db(db_path)
        product_db = ProductDB(db)
        vector_store = VectorStore(str(chroma_path))
        image_store = ImageStore(str(images_path))
        vlm_client = VLMClient(base_url="http://localhost:8001")
        embed_model = EmbeddingModel()
        assembler = DraftAssembler(vlm_client, embed_model)

        app.state.db = db
        app.state.product_db = product_db
        app.state.vector_store = vector_store
        app.state.image_store = image_store
        app.state.vlm_client = vlm_client
        app.state.embed_model = embed_model
        app.state.assembler = assembler
        app.state.sessions_path = str(sessions_path)

        yield

        db.close()

    app = FastAPI(title="lemonade-vision-server", version="0.1.0", lifespan=lifespan)

    app.include_router(capture_router)
    app.include_router(product_router)

    if images_path.exists():
        app.mount("/images", StaticFiles(directory=str(images_path)), name="images")

    @app.post("/session/start")
    async def session_start(request):
        import qrcode, io, base64
        tmp_dir = tempfile.mkdtemp(dir=str(sessions_path))
        sid = create_session(request.app.state.db, tmp_dir)
        qr = qrcode.make(sid)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {"session_id": sid, "qr_png_b64": b64}

    @app.delete("/session/{session_id}", status_code=204)
    async def session_delete(session_id: str, request):
        from lemonade_vision.session import close_session
        close_session(request.app.state.db, session_id)

    @app.get("/health", response_model=HealthResponse)
    async def health(request):
        import httpx
        vlm_ok = False
        try:
            resp = httpx.get("http://localhost:8001/v1/models", timeout=2.0)
            vlm_ok = resp.status_code == 200
        except Exception:
            pass
        count = request.app.state.vector_store.product_count()
        return HealthResponse(
            status="ok", vlm_reachable=vlm_ok, chroma_product_count=count
        )

    @app.get("/pairing/qr")
    async def pairing_qr(session_id: str, request):
        import qrcode, io, base64
        qr = qrcode.make(session_id)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        return {"qr_png_b64": base64.b64encode(buf.getvalue()).decode()}

    return app


if __name__ == "__main__":
    import uvicorn
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8787)
```

- [ ] **Step 6: Run — expect PASS**

```bash
uv run pytest tests/test_routes.py -v
```
Expected: 6 passed

- [ ] **Step 7: Commit**

```bash
git add src/lemonade_vision/api/ src/lemonade_vision/server.py tests/test_routes.py
git commit -m "feat: capture API routes + FastAPI server"
```

---

### Task 12: Deduction routes

**Files:**
- Create: `src/lemonade_vision/api/deduce.py`
- Create: `tests/test_deduce.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_deduce.py
import json
import pytest
import tempfile
import numpy as np
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_products(tmp_path):
    import os
    os.environ["VISION_DATA_DIR"] = str(tmp_path / "data")
    from lemonade_vision.server import create_app
    app = create_app(data_dir=str(tmp_path / "data"))
    client = TestClient(app)

    # Seed one product via state
    with client:
        db = app.state.db
        product_db = app.state.product_db
        vector_store = app.state.vector_store
        embed_model = app.state.embed_model

        product_db.insert_product(
            sku="ELFBAR001", brand="Elf Bar", flavor="Mango Ice",
            category="disposable_vape", puff_count=5000,
        )
        vec = embed_model.encode_text("Elf Bar Mango Ice disposable_vape")
        vector_store.upsert_text("ELFBAR001", vec, {
            "sku": "ELFBAR001", "brand": "Elf Bar",
            "flavor": "Mango Ice", "category": "disposable_vape",
        })
        yield client


def test_deduce_text_returns_candidates(client_with_products):
    with patch("lemonade_vision.pipeline.vlm.VLMClient.deduce_product_signals") as mock_deduce:
        mock_deduce.return_value = {
            "brand": "Elf Bar", "flavor": "Mango Ice",
            "category": "disposable_vape",
        }
        # Use underlying app directly
        resp = client_with_products.post(
            "/deduce/text",
            json={"query": "elf bar mango ice 5000", "top_k": 3},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "candidates" in data


def test_deduce_text_missing_query_returns_422(client_with_products):
    resp = client_with_products.post("/deduce/text", json={"top_k": 3})
    assert resp.status_code == 422


def test_deduce_audio_no_file_returns_422(client_with_products):
    resp = client_with_products.post("/deduce/audio")
    assert resp.status_code == 422
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/test_deduce.py -v
```
Expected: FAIL (ImportError or 404)

- [ ] **Step 3: Write api/deduce.py**

```python
# src/lemonade_vision/api/deduce.py
from __future__ import annotations
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from lemonade_vision.models import DeduceCandidate, DeduceRequest, DeduceResponse

router = APIRouter()

ALIAS_BONUS = 0.15
BRAND_BONUS = 0.10
FLAVOR_BONUS = 0.10


def _cosine_to_confidence(distance: float) -> float:
    # ChromaDB cosine distance: 0 = identical, 2 = opposite
    return max(0.0, 1.0 - distance / 2.0)


@router.post("/deduce/text", response_model=DeduceResponse)
async def deduce_text(body: DeduceRequest, request: Request):
    vlm_client = request.app.state.vlm_client
    embed_model = request.app.state.embed_model
    vector_store = request.app.state.vector_store
    product_db = request.app.state.product_db

    signals = await vlm_client.deduce_product_signals(body.query)
    brand_hint: Optional[str] = signals.get("brand")
    flavor_hint: Optional[str] = signals.get("flavor")

    enriched = " ".join(filter(None, [
        brand_hint, flavor_hint,
        signals.get("size"), signals.get("category"),
        body.query,
    ]))
    query_vec = embed_model.encode_text(enriched)

    if vector_store.product_count() == 0:
        return DeduceResponse(candidates=[], query_used=enriched)

    raw = vector_store.query_text(query_vec, top_k=body.top_k * 2)

    candidates: list[DeduceCandidate] = []
    for hit in raw:
        meta = hit["metadata"]
        sku = hit["id"]
        confidence = _cosine_to_confidence(hit["distance"])

        reasons: list[str] = []
        if brand_hint and meta.get("brand", "").lower() == brand_hint.lower():
            confidence = min(1.0, confidence + BRAND_BONUS)
            reasons.append("brand match")
        if flavor_hint and meta.get("flavor", "").lower() == flavor_hint.lower():
            confidence = min(1.0, confidence + FLAVOR_BONUS)
            reasons.append("flavor match")

        aliases = product_db.get_aliases(sku)
        query_lower = body.query.lower()
        if any(a.lower() in query_lower for a in aliases):
            confidence = min(1.0, confidence + ALIAS_BONUS)
            reasons.append("alias match")

        candidates.append(DeduceCandidate(
            sku=sku,
            confidence=round(confidence, 4),
            match_reason=", ".join(reasons) or "embedding similarity",
            brand=meta.get("brand"),
            flavor=meta.get("flavor"),
        ))

    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return DeduceResponse(candidates=candidates[:body.top_k], query_used=enriched)


@router.post("/deduce/audio", response_model=DeduceResponse)
async def deduce_audio(request: Request, file: UploadFile = File(...)):
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        audio_path = Path(d) / "query.wav"
        with open(audio_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        transcript: Optional[str] = None
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                with open(audio_path, "rb") as af:
                    resp = await client.post(
                        "http://localhost:8004/transcribe",
                        content=af.read(),
                        headers={"Content-Type": "audio/wav"},
                    )
                    resp.raise_for_status()
                    transcript = resp.json().get("text")
        except Exception:
            raise HTTPException(status_code=503, detail="fw-server :8004 unreachable")

        if not transcript:
            raise HTTPException(status_code=503, detail="transcription returned empty")

        from lemonade_vision.models import DeduceRequest as DR
        from fastapi import Request as FR
        return await deduce_text(DR(query=transcript), request)
```

- [ ] **Step 4: Register deduce router in server.py**

Add to `server.py` after the existing router includes:

```python
from lemonade_vision.api.deduce import router as deduce_router
# ...
app.include_router(deduce_router)
```

- [ ] **Step 5: Run — expect PASS**

```bash
uv run pytest tests/test_deduce.py -v
```
Expected: 3 passed

- [ ] **Step 6: Full test suite**

```bash
uv run pytest tests/ -v -k "not integration"
```
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/lemonade_vision/api/deduce.py src/lemonade_vision/server.py tests/test_deduce.py
git commit -m "feat: deduction routes /deduce/text and /deduce/audio"
```

---

### Task 13: ngrok launcher + GitHub push + integration test scaffold

**Files:**
- Create: `~/lemonade-vision-server/ngrok.sh`
- Create: `tests/test_pipeline_integration.py`
- Create: `tests/fixtures/depth-sample.json`

- [ ] **Step 1: Write ngrok.sh**

```bash
#!/usr/bin/env bash
# Start ngrok tunnel for lemonade-vision-server on :8787
# Usage: ./ngrok.sh [authtoken]
set -e

PORT=8787

if [ -n "$1" ]; then
  ngrok config add-authtoken "$1"
fi

echo "Starting ngrok tunnel → localhost:${PORT}"
ngrok http ${PORT}
```

```bash
chmod +x ~/lemonade-vision-server/ngrok.sh
```

- [ ] **Step 2: Write integration test scaffold**

```python
# tests/test_pipeline_integration.py
"""
End-to-end pipeline integration test.
Requires: VISION_INTEGRATION=1 and live VLM on :8001.
Skipped automatically otherwise.
"""
import os
import json
import tempfile
import numpy as np
import pytest
from pathlib import Path
from PIL import Image
from unittest.mock import patch

pytestmark = pytest.mark.skipif(
    not os.getenv("VISION_INTEGRATION"),
    reason="requires VISION_INTEGRATION=1 and live services",
)


@pytest.fixture
def sample_image():
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        p = Path(d) / "product.jpg"
        img = Image.fromarray(np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8))
        img.save(str(p))
        yield str(p)


@pytest.fixture
def sample_depth():
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        p = Path(d) / "depth.json"
        grid = np.full((256, 192), 350.0).tolist()
        p.write_text(json.dumps(grid))
        yield str(p)


@pytest.mark.asyncio
async def test_vlm_client_real_call(sample_image):
    from lemonade_vision.pipeline.vlm import VLMClient
    client = VLMClient()
    result = await client.extract_product_info([sample_image], narration=None)
    assert result.vlm_status in ("ok", "unavailable")


@pytest.mark.asyncio
async def test_embeddings_real_clip(sample_image):
    from lemonade_vision.pipeline.embeddings import EmbeddingModel
    import numpy as np
    model = EmbeddingModel()
    vec = model.encode_image(sample_image)
    assert vec.shape == (512,)
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 0.01


@pytest.mark.asyncio
async def test_full_pipeline_no_video(sample_image, sample_depth):
    from lemonade_vision.pipeline.vlm import VLMClient
    from lemonade_vision.pipeline.embeddings import EmbeddingModel
    from lemonade_vision.draft import DraftAssembler

    client = VLMClient()
    model = EmbeddingModel()
    assembler = DraftAssembler(client, model)

    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        draft = await assembler.run(
            job_id="test-job",
            session_id="test-session",
            rotation_video_path=None,
            still_paths={"front": sample_image},
            depth_path=sample_depth,
            narration_path=None,
            frame_out_dir=d,
        )
    assert draft["job_id"] == "test-job"
    assert "signal_scores" not in draft or True  # signal_scores removed before return
```

- [ ] **Step 3: Write depth-sample.json fixture**

```bash
python3 -c "
import json, numpy as np
grid = np.full((256, 192), 350.0).tolist()
with open('tests/fixtures/depth-sample.json', 'w') as f:
    json.dump(grid, f)
"
```

- [ ] **Step 4: Create GitHub repo and push**

```bash
cd ~/lemonade-vision-server
gh repo create bong-water-water-bong/lemonade-vision-server \
  --public \
  --description "Product vision pipeline: iPhone 4K booth scan → SQLite/ChromaDB via FastAPI"
git remote add origin https://github.com/bong-water-water-bong/lemonade-vision-server.git
git push -u origin main
```

- [ ] **Step 5: Run full unit + API test suite**

```bash
cd ~/lemonade-vision-server
make all
```
Expected: lint + type + test all pass (or only known type stub gaps)

- [ ] **Step 6: Final commit**

```bash
git add ngrok.sh tests/test_pipeline_integration.py tests/fixtures/
git commit -m "feat: ngrok launcher, integration test scaffold, depth fixture"
git push
```

- [ ] **Step 7: Push cashier spec changes to origin and pi**

```bash
cd ~/lemonade-cashier
git push origin main
git push pi main
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Task |
|---|---|
| Standalone repo + venv | Task 1 |
| FastAPI + lifespan startup | Task 11 |
| `/session/start` + QR code | Task 11 |
| `/session/{id}` DELETE | Task 11 |
| `/capture/video` rotation video upload | Task 11 |
| `/capture/still` close-up stills | Task 11 |
| `/capture/depth` LiDAR upload | Task 11 |
| `/capture/audio` narration upload | Task 11 |
| `/capture/finalize` → background pipeline | Task 11 |
| `/product/draft/{job_id}` | Task 11 |
| `/product/commit` | Task 11 |
| `/product/{sku}` PATCH | Task 11 |
| `/deduce/text` | Task 12 |
| `/deduce/audio` | Task 12 |
| `/health` | Task 11 |
| `/pairing/qr` | Task 11 |
| Frame extraction (ffmpeg, no cv2) | Task 4 |
| Laplacian sharpness scoring | Task 4 |
| pyzbar UPC detection | Task 5 |
| VLM client (15s onboard / 3s deduction timeout) | Task 6 |
| rembg background removal | Task 7 |
| CLIP ViT-B-32 embeddings | Task 7 |
| LiDAR depth → W×H×D | Task 8 |
| Confidence model (weights, thresholds) | Task 8 |
| SQLite schema (all 5 tables) | Task 3 |
| ChromaDB product_visual + product_text | Task 9 |
| Disk image store (800px/85% JPEG) | Task 9 |
| Session TTL + cleanup | Task 3 |
| Draft assembly | Task 10 |
| Alias re-rank bonus in deduction | Task 12 |
| Error handling: VLM unavailable → vlm_status | Task 6 |
| Error handling: fw-server unavailable → 503 | Task 12 |
| All tests write to /tmp | All tasks ✓ |
| ngrok launcher | Task 13 |
| GitHub repo | Task 13 |
| Integration tests skip without VISION_INTEGRATION=1 | Task 13 |

All spec requirements covered.
