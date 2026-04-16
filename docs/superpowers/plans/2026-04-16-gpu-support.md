# GPU-Support Integration — Plan

## Steps

1. **Config erweitern** — `device`, `batch_size`, `dtype` in `EmbeddingConfig`
2. **GPU Detection** — `detect_device()` Funktion in `sentence_transformers.py`
3. **Provider erweitern** — Device/dtype/batch_size im SentenceTransformersProvider
4. **SDPA Detection** — Backend-Check beim Warmup, AOTriton Env-Variable
5. **Indexer** — `_BATCH_SIZE` durch Config-Wert ersetzen
6. **Provider Factory** — `get_provider()` neue Config-Felder durchreichen
7. **Benchmark** — Script für GPU + Batch-Size-Vergleich
8. **Tests** — Bestehende Tests anpassen
9. **Manueller Test** — ROCm auf André's System
