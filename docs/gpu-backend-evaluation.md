# GPU Backend Evaluation: ONNX Runtime for Mneme

**Stand:** April 2026
**Kontext:** Mneme nutzt BGE-M3 (1024-dim) Embeddings. Aktuell via sentence-transformers (PyTorch) — ~2 GB RAM, ~18 Min CPU-Indexierung für 154 Notizen.

## Backend-Vergleich

| Backend | OS | GPU-Vendor | Package | Verfügbarkeit | Perf. vs PyTorch CPU | Status |
|---------|-----|-----------|---------|--------------|---------------------|--------|
| **CPU** | Win/Linux/Mac | - | `onnxruntime` | Sofort nutzbar | ~1.5-2x schneller | Stabil, Production-ready |
| **DirectML** | Windows | AMD, Intel, NVIDIA | `onnxruntime-directml` | Sofort nutzbar | ~3-5x schneller | Maintenance Mode (WinML empfohlen) |
| **CUDA** | Win/Linux | NVIDIA | `onnxruntime-gpu` | CUDA Toolkit nötig | ~5-10x schneller | Stabil, Best Support |
| **ROCm** | Linux only | AMD (RDNA3/4) | `onnxruntime-rocm` | ROCm 7.0+ nötig | ~4-8x schneller | EP entfernt ab ORT 1.23 → MIGraphX |
| **Vulkan** | - | - | - | **Existiert nicht** | - | Nur Feature-Requests, kein EP |

## Detailbewertung

### CPU (onnxruntime)
- **Empfehlung: Default für alle User**
- ONNX Runtime auf CPU ist ~1.5-2x schneller als PyTorch für Transformer-Inference
- INT8-Quantisierung bringt nochmal ~2-3x Speedup (insgesamt ~3-6x vs PyTorch)
- Keine zusätzlichen Treiber/SDKs nötig
- `pip install onnxruntime`

### DirectML (onnxruntime-directml)
- **Empfehlung: AMD-User auf Windows**
- Nutzt DirectX 12 — funktioniert mit allen DX12-fähigen GPUs (AMD, NVIDIA, Intel)
- Guter Weg für AMD-GPUs auf Windows, da ROCm nur Linux unterstützt
- **Achtung:** DirectML ist seit 2026 in "Maintenance Mode" — Microsoft empfiehlt WinML als Nachfolger
- `pip install onnxruntime-directml`

### CUDA (onnxruntime-gpu)
- **Empfehlung: NVIDIA-User mit CUDA-Setup**
- Bester Support, beste Performance, meiste Dokumentation
- Benötigt CUDA Toolkit + cuDNN
- IOBinding für optimierte GPU-Memory-Transfers verfügbar
- `pip install onnxruntime-gpu`

### ROCm (onnxruntime-rocm)
- **Nur Linux, nur AMD Instinct/RDNA3+**
- ROCm Execution Provider wurde ab ORT 1.23 entfernt
- Migration zu MIGraphX Execution Provider empfohlen
- Unterstützt: RDNA 3 (RX 7000), RDNA 4 (RX 9000), Instinct MI-Serie
- Komplexes Setup (ROCm 7.0+ erforderlich)

### Vulkan
- **Existiert nicht als ONNX Runtime Execution Provider**
- Mehrere Feature-Requests auf GitHub (Issues #7433, #10603, #21917)
- Keine Aktivität seitens Microsoft — unwahrscheinlich in naher Zukunft
- Alternative: WebGPU EP (nur für Browser/Web-Umgebungen)

## BGE-M3 ONNX-Modell

BGE-M3 ist als ONNX-Modell verfügbar:

| Repo | Format | Optimierung | Größe |
|------|--------|------------|-------|
| [aapot/bge-m3-onnx](https://huggingface.co/aapot/bge-m3-onnx) | FP32 | O2 Graph Opt. | ~2.2 GB |
| [gpahal/bge-m3-onnx-int8](https://huggingface.co/gpahal/bge-m3-onnx-int8) | INT8 | Quantisiert | ~600 MB |
| [philipchung/bge-m3-onnx](https://huggingface.co/philipchung/bge-m3-onnx) | FP32 | Standard | ~2.2 GB |

**Hinweis:** sentence-transformers (ab v3.0) unterstützt `backend="onnx"` nativ — damit kann BGE-M3 auch ohne separaten ONNX-Export direkt als ONNX geladen werden.

## FastEmbed Alternative

[FastEmbed](https://github.com/qdrant/fastembed) von Qdrant unterstützt BGE-M3 (`BAAI/bge-m3`). Es nutzt ONNX Runtime intern und liefert quantisierte Modelle. Allerdings ist es eine zusätzliche Dependency und bietet weniger Kontrolle über Backend-Auswahl.

## Installation pro Backend

### CPU (Standard)
```bash
pip install mneme[onnx]
```

Config (`config.toml`):
```toml
[embedding]
provider = "onnx"
model = "BAAI/bge-m3"
backend = "cpu"
```

### DirectML (AMD/Intel/NVIDIA auf Windows)
```bash
pip install mneme[directml]
```

Config:
```toml
[embedding]
provider = "onnx"
model = "BAAI/bge-m3"
backend = "directml"
```

### CUDA (NVIDIA)
```bash
pip install mneme[cuda]
```

Config:
```toml
[embedding]
provider = "onnx"
model = "BAAI/bge-m3"
backend = "cuda"
```

**Voraussetzung:** CUDA Toolkit 12.x + cuDNN 9.x installiert.

### ROCm (AMD auf Linux)
```bash
pip install onnxruntime-rocm  # oder migraphx
```

Config:
```toml
[embedding]
provider = "onnx"
model = "BAAI/bge-m3"
backend = "rocm"
```

**Voraussetzung:** ROCm 7.0+ installiert, nur Linux, RDNA3/4 oder MI-Serie.

## Empfehlung

| Use Case | Backend |
|----------|---------|
| **Schnellster Start, kein GPU** | `cpu` mit ONNX (1.5-2x schneller als PyTorch) |
| **AMD GPU auf Windows** | `directml` |
| **NVIDIA GPU** | `cuda` |
| **AMD GPU auf Linux** | `rocm` (mit MIGraphX EP) |
| **Maximale Kompatibilität** | `cpu` — funktioniert überall |
| **Kleinstmöglicher RAM** | `cpu` mit INT8-Modell (gpahal/bge-m3-onnx-int8) |
