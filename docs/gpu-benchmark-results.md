# Mneme GPU Backend Benchmark — Echte Messungen

**System:** AMD Ryzen (64 GB RAM), AMD Radeon RX 7900 XTX (24 GB VRAM), Windows 11
**Vault:** 154 Notizen, 1152 Chunks, BGE-M3 (1024 Dim)
**Datum:** 2026-04-16

## Ergebnisse

| Backend | Embed Time | Chunks/s | RAM Peak | Search | Status |
|---|---|---|---|---|---|
| **PyTorch CPU** (isoliert) | **1254s** (21 Min) | **0.9** | **7.6 GB** | **56ms** | **Stabil — Empfohlen** |
| ONNX CPU (aapot/bge-m3-onnx) | 1637s (27 Min) | 0.7 | 31 GB | 25ms | Langsamer, 4x mehr RAM |
| ONNX INT8 CPU (xenova/bge-m3) | >20 Min, abgebrochen | — | **39 GB** | — | OOM-Risiko, unbrauchbar |
| ONNX + DirectML (FP32) | CRASH | — | — | — | Attention-Op nicht unterstützt |
| ONNX INT8 + DirectML | CRASH | — | — | — | FusedMatMul "Falscher Parameter" |

## Analyse

### PyTorch CPU — Klarer Sieger
- 1254s (21 Min) für Full Reindex, 0.9 Chunks/s
- 7.6 GB RAM — handhabbar auf 64 GB System
- 56ms Suchzeit pro Query
- Stabil, vorhersagbar, keine Surprises

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

### Jetzt: PyTorch CPU beibehalten
Kein Backend-Wechsel. PyTorch CPU ist stabil, am schnellsten, und verbraucht am wenigsten RAM. Der Full Reindex dauert 21 Min, aber Incremental ist 0.2s — für den Normalbetrieb kein Problem.

### Für GPU-Beschleunigung (Zukunft)
1. **PyTorch + ROCm auf WSL2** — sentence-transformers direkt mit AMD GPU, kein ONNX nötig. Vielversprechendster Weg.
2. **Kleineres Modell** auf DirectML — `multilingual-e5-small` (120 MB, 384 Dim) funktioniert auf DirectML, aber Qualitäts-Tradeoff. Nur sinnvoll wenn Full Reindex häufig nötig ist.
3. **NVIDIA CUDA** — Für User mit NVIDIA GPU: `pip install torch --index-url https://download.pytorch.org/whl/cu124` → sentence-transformers nutzt CUDA automatisch, 5-10x Speedup.

### Config-Empfehlung für Mneme
```toml
[embedding]
provider = "sentence-transformers"  # Nicht onnx — PyTorch ist schneller
model = "BAAI/bge-m3"
# backend wird ignoriert bei sentence-transformers (auto-detect CPU/CUDA)
```
