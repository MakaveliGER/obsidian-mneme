# Mneme GPU Backend Benchmark — Echte Messungen

**System:** AMD Ryzen (64 GB RAM), AMD Radeon RX 7900 XTX (24 GB VRAM), Windows 11
**Vault:** 154 Notizen, 1162 Chunks, BGE-M3 (1024 Dim)
**Datum:** 2026-04-16

## Ergebnisse

### Runde 1 — Backend-Vergleich (bfloat16, bs=32)

| Backend | Embed Time | Chunks/s | RAM/VRAM Peak | Search | Status |
|---|---|---|---|---|---|
| PyTorch CPU (FP32) | 1254s (21 Min) | 0.9 | 7.6 GB RAM | 56ms | Baseline |
| PyTorch CPU (bfloat16 + SDPA) | 1029s (17 Min) | 1.1 | 7.0 GB RAM | 75ms | Default v0.2.0 |
| ONNX CPU (aapot/bge-m3-onnx) | 1637s (27 Min) | 0.7 | 31 GB RAM | 25ms | 4x mehr RAM |
| ONNX + DirectML | CRASH | — | — | — | Attention-Op nicht unterstützt |
| PyTorch ROCm GPU (bfloat16 bs=32) | 15.6s | 74.4 | 3.4 GB VRAM | 47ms | 66x Speedup |
| **PyTorch ROCm GPU (float16 bs=32)** | **11.9s** | **97.6** | **3.4 GB VRAM** | **20ms** | **87x Speedup** |

### Runde 2 — GPU Batch Size Optimierung (bfloat16)

| Batch Size | Embed Time | Chunks/s | VRAM Peak | Ergebnis |
|---|---|---|---|---|
| **32** | **15.6s** | **74.4** | **3.4 GB** | **Optimal** |
| 64 | 30.5s | 38.1 | 5.7 GB | 2x langsamer |
| 128 | 88.0s | 13.2 | 10.3 GB | 5.6x langsamer |
| 256 | 204.0s | 5.7 | 19.4 GB | 13x langsamer |

**Erkenntnis:** Größere Batch Sizes sind LANGSAMER, nicht schneller. BGE-M3 hat variable Sequenzlängen — größere Batches = mehr Padding = mehr Verschwendung. Default bleibt 32.

### Runde 3 — GPU dtype Vergleich (bs=32)

| dtype | Embed Time | Chunks/s | VRAM Peak | Ergebnis |
|---|---|---|---|---|
| **float16** | **11.9s** | **97.6** | **3.4 GB** | **Neuer Default** |
| bfloat16 | 15.6s | 74.4 | 3.4 GB | 31% langsamer |
| float32 | 160.2s | 7.3 | 6.5 GB | 13x langsamer |

**Erkenntnis:** float16 ist auf AMD RDNA3 31% schneller als bfloat16. Neuer Default.

### SDPA Backend Detection (Windows ROCm, gfx1100)

| Backend | Status |
|---|---|
| flash | FAIL |
| mem_efficient | FAIL |
| math | OK |

AOTriton (`TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`) hat keinen messbaren Impact — Flash/mem_efficient bleiben auf gfx1100 Windows nicht verfügbar. Trotzdem 87x Speedup mit math-only SDPA.

## Analyse

### GPU float16 bs=32 — Klarer Sieger
- **11.9s** für 1162 Chunks = **97.6 ch/s**
- **87x schneller als CPU** (1029s → 11.9s)
- **3.4 GB VRAM** — nur 14% der verfügbaren 24 GB
- 20ms Search-Latenz (besser als CPU's 75ms)
- Kein Qualitätsverlust: float16 hat ausreichend Precision für Retrieval-Embeddings

### Warum größere Batch Sizes langsamer sind
BGE-M3 verarbeitet Texte mit variabler Sequenzlänge (50-500 Tokens). Bei batch_size=256 wird jeder Text im Batch auf die Länge des längsten gepaddet. Das erzeugt massive Verschwendung — eine Batch mit einem 500-Token-Dokument und 255 kurzen 50-Token-Dokumenten berechnet 256 × 500 = 128.000 Tokens statt der tatsächlichen ~13.000 Tokens.

### Alle ONNX-Varianten — Nicht empfehlenswert für BGE-M3
BGE-M3's Attention-Layer (`FusedMatMul`, `Attention` Ops) ist nicht kompatibel mit DirectML. CPU ONNX ist 22% langsamer als PyTorch und braucht 4x mehr RAM.

## Config-Empfehlung

### Optimale GPU-Config (AMD ROCm)
```toml
[embedding]
provider = "sentence-transformers"
model = "BAAI/bge-m3"
device = "auto"      # erkennt GPU automatisch
batch_size = 32      # optimal für BGE-M3
dtype = "float16"    # 31% schneller als bfloat16 auf AMD
```

### CPU-Config (Fallback)
```toml
[embedding]
provider = "sentence-transformers"
model = "BAAI/bge-m3"
device = "cpu"
batch_size = 32
dtype = "bfloat16"   # bfloat16 ist auf CPU 22% schneller als float32
```

### ROCm Installation (Windows, RX 7900 XTX)
```bash
# 1. HIP SDK installieren (GUI, Admin nötig)
# 2. Python 3.12 venv
uv venv .venv-rocm --python 3.12

# 3. ROCm SDK + PyTorch (Version muss zur HIP SDK passen)
uv pip install --python .venv-rocm/Scripts/python.exe --no-deps \
  https://repo.radeon.com/rocm/windows/rocm-rel-7.1.1/rocm_sdk_core-0.1.dev0-py3-none-win_amd64.whl \
  https://repo.radeon.com/rocm/windows/rocm-rel-7.1.1/rocm_sdk_devel-0.1.dev0-py3-none-win_amd64.whl \
  https://repo.radeon.com/rocm/windows/rocm-rel-7.1.1/rocm_sdk_libraries_custom-0.1.dev0-py3-none-win_amd64.whl \
  https://repo.radeon.com/rocm/windows/rocm-rel-7.1.1/torch-2.9.0+rocmsdk20251116-cp312-cp312-win_amd64.whl
uv pip install --python .venv-rocm/Scripts/python.exe sentence-transformers

# 4. Mneme installieren
uv pip install --python .venv-rocm/Scripts/python.exe -e .
```

### Für NVIDIA-User
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
# device=auto erkennt CUDA automatisch
```
