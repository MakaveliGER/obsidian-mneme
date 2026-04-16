# Mneme GPU Backend Benchmark — Echte Messungen

**System:** AMD Ryzen (64 GB RAM), AMD Radeon RX 7900 XTX (24 GB VRAM), Windows 11
**Vault:** 154 Notizen, 1152 Chunks, BGE-M3 (1024 Dim)
**Datum:** 2026-04-16

## Ergebnisse

| Backend | Embed Time | Chunks/s | RAM (Peak) | Search (avg) | Status |
|---|---|---|---|---|---|
| **PyTorch CPU** (Baseline) | **1309s** (~22 Min) | 0.9 | 7.6 GB | 68.8ms | Stabil |
| ONNX Runtime CPU | 1637s (~27 Min) | 0.7 | 31.3 GB | 25.0ms | Langsamer als PyTorch |
| ONNX + DirectML (AMD GPU) | — | — | — | — | CRASH: "nicht genügend Speicherressourcen" |

## Analyse

### PyTorch CPU (Baseline) — Empfohlen für jetzt
- Stabil, vorhersagbar, 0.9 Chunks/s
- 7.6 GB RAM ist hoch aber handhabbar auf 64 GB System
- Suchzeit 68.8ms ist schnell genug

### ONNX Runtime CPU — Nicht empfohlen
- **Langsamer als PyTorch** (0.7 vs 0.9 Chunks/s = -22%)
- **31 GB RAM** — das `aapot/bge-m3-onnx` Modell ist nicht optimiert
- Einziger Vorteil: Suchzeit 25ms (37% schneller bei Single-Query)
- Problem: Der ONNX-Export von BGE-M3 ist nicht performance-optimiert (kein Quantization, kein Graph-Optimization)

### DirectML — Nicht nutzbar mit BGE-M3
- BGE-M3 hat einen großen Attention-Layer (8192 Max Seq Length, 1024 Hidden)
- DirectML Attention-Op kann den VRAM-Bedarf nicht allokieren
- Error: `Für diesen Vorgang sind nicht genügend Speicherressourcen verfügbar`
- **Auch mit 24 GB VRAM crasht es** — das liegt an DirectML's Speichermanagement, nicht am VRAM

## Empfehlung

### Jetzt: PyTorch CPU beibehalten
Das bestehende sentence-transformers Backend ist die stabilste und schnellste Option auf CPU. Kein Wechsel nötig.

### Für GPU-Beschleunigung: Kleineres Modell oder PyTorch ROCm
1. **Kleineres ONNX-Modell** (z.B. `bge-small-en-v1.5`, 384 Dim) würde auf DirectML laufen — aber Qualitätsverlust
2. **PyTorch + ROCm nativ auf Windows** (PyTorch 2.9.1 + ROCm 7.2.1) — sentence-transformers würde direkt GPU nutzen, kein ONNX-Export nötig
3. **Quantisiertes BGE-M3 ONNX** (INT8) — könnte DirectML-kompatibel sein, bräuchte Custom-Export

### Für die Community (NVIDIA)
`onnxruntime-gpu` (CUDA) oder direkt sentence-transformers mit CUDA — "just works" und 5-10x schneller.
