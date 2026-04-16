# GPU-Support Integration — Design Spec

## Problem
GPU-Beschleunigung ist benchmarked (ROCm: 9.5x Speedup), aber nicht in Mneme integriert. Device, Batch Size und dtype sind hardcoded. Kein automatisches GPU-Detection.

## Lösung

### Config-Erweiterung (`EmbeddingConfig`)
```toml
[embedding]
provider = "sentence-transformers"
model = "BAAI/bge-m3"
device = "auto"       # "auto" | "cpu" | "cuda"
batch_size = 32       # 32-256, abhängig von VRAM
dtype = "bfloat16"    # "float32" | "float16" | "bfloat16"
```

### Dynamic Backend Detection (`device = "auto"`)
Hierarchisch:
1. `torch.cuda.is_available()` → True?
2. `torch.cuda.get_device_name(0)` → enthält "Radeon"/"AMD"? → ROCm-Modus (setze `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`)
3. Sonst → CUDA/NVIDIA-Modus
4. Alles fehl → CPU mit Warning

Ergebnis: Resolved device string ("cuda" oder "cpu") + is_rocm Flag.

### SDPA Backend Detection (Startup-Log)
Beim Warmup testen welche SDPA-Backends verfügbar sind:
- `flash_sdp`: WORKS/FAILED
- `mem_efficient_sdp`: WORKS/FAILED
- `math_sdp`: WORKS/FAILED

Nur logging, kein Runtime-Impact.

### AOTriton
Wenn ROCm erkannt → `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1` setzen (vor Model Load).

### Batch Size
- Config-Wert wird an Indexer durchgereicht (statt hardcoded `_BATCH_SIZE = 32`)
- Default bleibt 32 (safe für CPU + kleine GPUs)
- GPU-Empfehlung: 128-256 bei 24GB VRAM

### dtype Mapping
| Config | torch dtype |
|--------|------------|
| `"float32"` | `torch.float32` |
| `"float16"` | `torch.float16` |
| `"bfloat16"` | `torch.bfloat16` |

## Betroffene Dateien
- `src/mneme/config.py` — EmbeddingConfig erweitern
- `src/mneme/embeddings/__init__.py` — Config-Felder durchreichen
- `src/mneme/embeddings/sentence_transformers.py` — Device/dtype/SDPA-Detection
- `src/mneme/indexer.py` — Batch Size aus Config statt hardcoded
- `scripts/benchmark.py` — GPU-Modi + Batch-Size-Vergleich

## Nicht-Ziele
- ONNX DirectML Fallback (funktioniert nicht für BGE-M3)
- Flash Attention 2 Package (nicht verfügbar auf Windows ROCm)
- torch.compile() (experimentell, separater Task)
