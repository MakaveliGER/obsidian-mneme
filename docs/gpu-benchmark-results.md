# Mneme GPU Backend Benchmark — Echte Messungen

**System:** AMD Ryzen (64 GB RAM), AMD Radeon RX 7900 XTX (24 GB VRAM), Windows 11
**Vault:** 154 Notizen, 1152 Chunks, BGE-M3 (1024 Dim)
**Datum:** 2026-04-16

## Ergebnisse

| Backend | Embed Time | Chunks/s | RAM Peak | Search | Status |
|---|---|---|---|---|---|
| PyTorch CPU (FP32) | 1254s (21 Min) | 0.9 | 7.6 GB | 56ms | Baseline |
| **PyTorch CPU (bfloat16 + SDPA)** | **1029s (17 Min)** | **1.1** | **7.0 GB** | **75ms** | **Empfohlen — Default** |
| ONNX CPU (aapot/bge-m3-onnx) | 1637s (27 Min) | 0.7 | 31 GB | 25ms | Langsamer, 4x mehr RAM |
| ONNX INT8 CPU (xenova/bge-m3) | >20 Min, abgebrochen | — | 39 GB | — | OOM-Risiko |
| ONNX + DirectML (FP32) | CRASH | — | — | — | Attention-Op nicht unterstützt |
| ONNX INT8 + DirectML | CRASH | — | — | — | FusedMatMul "Falscher Parameter" |
| **PyTorch ROCm GPU (RX 7900 XTX)** | **108s (1.8 Min)** | **10.7** | **12.8 GB** | **209ms** | **9.5x Speedup!** |

## Analyse

### PyTorch CPU bfloat16 + SDPA — Klarer Sieger
- **1029s (17 Min)** für Full Reindex, 1.1 Chunks/s — **22% schneller als FP32**
- **7.0 GB RAM** — 8% weniger als FP32
- 75ms Suchzeit pro Query (leicht höher als FP32, aber irrelevant)
- bfloat16 halbiert die Precision → schnellere MatMul, weniger Speicher
- SDPA (Scaled Dot-Product Attention) nutzt optimierte Flash-Attention-Kernels
- **Jetzt als Default im SentenceTransformersProvider aktiviert**

### Alle ONNX-Varianten — Nicht empfehlenswert für BGE-M3
BGE-M3 ist ein großes Modell (568M Parameter, 8192 Max Seq Length). Die verfügbaren ONNX-Exporte sind:

1. **aapot/bge-m3-onnx** (FP32, ~2.2 GB) — Funktioniert auf CPU, aber **langsamer** als PyTorch (0.7 vs 0.9 ch/s) und verbraucht **4x mehr RAM** (31 GB vs 7.6 GB). Kein Graph Optimization im Export.

2. **xenova/bge-m3** (INT8, ~680 MB Datei) — Trotz kleinerer Datei **explodiert der RAM** auf 39 GB während der Inference. Der quantisierte Export ist nicht für Batch-Processing optimiert.

3. **DirectML** — BGE-M3's Attention-Layer (`FusedMatMul`, `Attention` Ops) ist **nicht kompatibel** mit DirectML's Execution Provider. Crasht sowohl mit FP32 als auch INT8. Dies ist eine Limitation von DirectML, nicht von ONNX Runtime generell.

### Warum ONNX hier versagt
- BGE-M3 hat 8192 max seq length → große Attention-Matrizen
- Die ONNX-Exporte sind nicht mit `optimum` graph-optimiert
- DirectML unterstützt nicht alle Attention-Ops die BGE-M3 braucht
- PyTorch nutzt intern optimierte C++/BLAS-Kernels die ONNX Runtime nicht hat

## Empfehlung

### Jetzt: PyTorch CPU bfloat16 + SDPA (aktiviert als Default)
22% schneller als FP32, 8% weniger RAM. Automatisch aktiv seit v0.2.0. Full Reindex: 17 Min statt 21 Min. Incremental bleibt 0.2s.

### Nächster Schritt: PyTorch + ROCm (Python 3.12)
AMD ROCm 7.2.1 auf Windows unterstützt die RX 7900 XTX offiziell. Erwarteter Speedup: 5-15x.

**Status:** FUNKTIONIERT! 9.5x Speedup gemessen.

**Voraussetzungen:**
1. HIP SDK installieren: https://www.amd.com/en/developer/resources/rocm-hub/hip-sdk.html (kein PRO-Treiber nötig)
2. Python 3.12

**Installation (getestet, funktioniert):**
```bash
uv venv .venv-rocm --python 3.12
# ROCm SDK + PyTorch passend zur HIP SDK Version (7.1.1 für HIP 7.1)
uv pip install --python .venv-rocm/Scripts/python.exe --no-deps \
  https://repo.radeon.com/rocm/windows/rocm-rel-7.1.1/rocm_sdk_core-0.1.dev0-py3-none-win_amd64.whl \
  https://repo.radeon.com/rocm/windows/rocm-rel-7.1.1/rocm_sdk_devel-0.1.dev0-py3-none-win_amd64.whl \
  https://repo.radeon.com/rocm/windows/rocm-rel-7.1.1/rocm_sdk_libraries_custom-0.1.dev0-py3-none-win_amd64.whl \
  https://repo.radeon.com/rocm/windows/rocm-rel-7.1.1/torch-2.9.0+rocmsdk20251116-cp312-cp312-win_amd64.whl
uv pip install --python .venv-rocm/Scripts/python.exe sentence-transformers
```

**Hinweis:** ROCm SDK Version muss zur HIP SDK Version passen (7.1.1 für HIP 7.1, 7.2.1 für HIP 7.2).
SDPA Attention ist auf AMD noch experimentell — funktioniert aber korrekt.
VRAM wird als 43 GB reported (shared memory model bei AMD).

### Für NVIDIA-User
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu124
# sentence-transformers nutzt CUDA automatisch, 5-10x Speedup
```

### Config-Empfehlung
```toml
[embedding]
provider = "sentence-transformers"  # bfloat16 + SDPA automatisch aktiv
model = "BAAI/bge-m3"
```
