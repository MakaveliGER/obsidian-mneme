---
title: CI Fix — HuggingFace-Modelle für Server-Tests verfügbar machen
date: 2026-04-28
status: backlog
priority: medium
discovered_in: Mneme commit 740445d (KITS BM25-Fix push triggered failing CI)
---

# CI Fix — HF-Modelle für Server-Tests

## Problem

CI auf `master` ist seit mindestens commit `740445d` (2026-04-28) rot.
14 Tests failed, 312 passed — identisch auf allen 4 Runner-Configs
(Python 3.11/3.12 × ubuntu/windows). Failure ist **nicht durch den
Commit verursacht** — ein bestehendes Infrastruktur-Problem.

**Failure-Cluster:** alle 14 in `tests/test_server.py` und
`tests/test_gardener.py`. Symptom:

```
huggingface_hub.errors.LocalEntryNotFoundError:
  Cannot find the requested files in the disk cache and outgoing traffic
  has been disabled. To enable hf.co look-ups and downloads online,
  set 'local_files_only' to False.
OSError: We couldn't connect to 'https://huggingface.co' to load the files,
  and couldn't find them in the cached files.
```

Wenn der Server in den Test-Fixtures (`server_with_vault`, `gardener_setup`)
einen Embedding-Provider initialisiert, will dieser ein Modell laden.
Im CI-Env ist `local_files_only=True` gesetzt (HuggingFace-Default in
offline-Mode), und kein Modell ist vorgecached. Server-Init schlägt
fehl, alle Tests assertieren auf `'error' in result` statt
`'results' in result`.

`tests/test_store.py` (lokale FTS5/Vector-Tests, kein Provider) bleibt
grün — die BM25-Fix-Tests aus dem Commit sind nicht betroffen.

## Drei Lösungsvarianten

### Variante 1 — HF-Cache im Workflow (kleinste Änderung)

`.github/workflows/ci.yml` ergänzen mit:

```yaml
- name: Cache HuggingFace models
  uses: actions/cache@v4
  with:
    path: ~/.cache/huggingface
    key: hf-${{ runner.os }}-bge-m3-1.5
    restore-keys: |
      hf-${{ runner.os }}-bge-m3-
```

+ entweder `local_files_only=False` (online-Mode für ersten Cold-Run
und Cache-Refresh) oder ein dediziertes Pre-Warm-Step:

```yaml
- name: Pre-warm HF cache
  run: |
    python -c "from huggingface_hub import snapshot_download; \
      snapshot_download('BAAI/bge-m3', local_files_only=False)"
```

**Pro:** wenig Code-Änderung. Cache hält über Runs.
**Contra:** macht CI von HF-Verfügbarkeit abhängig (rate-limits, hf.co
Outages). Erster Cold-Run dauert ~5 Min Modell-Download.

### Variante 2 — `local_files_only=False` in Tests

Die Test-Fixtures (`tests/conftest.py` oder direkt in
`test_server.py`/`test_gardener.py`) explizit auf online stellen.

**Pro:** trivial.
**Contra:** wie 1, plus jeder einzelne Test-Run lädt potenziell neu.

### Variante 3 — Embedding-Provider mocken (sauberster Pattern)

Pytest-Fixture, die `mneme.embeddings.get_provider` mit einem
Stub-Provider patcht, der zufällige aber dimensions-korrekte Embeddings
liefert. Die Server-Tests testen dann Server-Logik, nicht
Modell-Verhalten.

**Beispiel-Skizze:**

```python
# tests/conftest.py
import pytest
import numpy as np
from unittest.mock import patch

class FakeProvider:
    def embed(self, texts):
        # 1024-dim zufällige Embeddings, deterministisch via hash
        rng = np.random.default_rng(42)
        return [rng.standard_normal(1024).tolist() for _ in texts]

@pytest.fixture
def fake_embedding_provider():
    with patch("mneme.embeddings.get_provider",
               return_value=FakeProvider()) as m:
        yield m
```

Dann `server_with_vault`-Fixture um diese Fixture erweitern.

**Pro:** echte Unit-Isolation, CI offline-fähig, schnellste Tests.
**Contra:** Mehr Refactor-Arbeit. Tests, die echte Embedding-Qualität
prüfen wollten (gibt's sowas in Mneme-Server-Tests?), müssen separat
gehalten werden.

## Empfehlung

**Variante 1** als Sofort-Fix (CI grün in <30 min). **Variante 3** als
Folge-Refactor wenn Tests öfter rot werden oder Modell-Download in CI
ein Bottleneck wird.

## Akzeptanz-Kriterien

- [ ] CI-Run auf `master` grün, alle 4 Runner-Configs (Python 3.11/3.12
      × ubuntu/windows)
- [ ] Test-Laufzeit nicht > 6 Min auf hosted runner (aktuell 1-3 Min,
      mit cold-start-HF-Download evtl. 5-7 Min)
- [ ] `tests/test_server.py::test_search_notes_returns_results` grün
- [ ] `tests/test_gardener.py::test_vault_health_selective_checks` grün

## Kontext / Verlauf

- 2026-04-28: KITS-Push (`740445d` BM25-Fix) triggerte CI-Run, der das
  bestehende Problem sichtbar machte. Diagnose im KITS-Repo dokumentiert
  unter `docs/research/2026-04-28-step1-step2-reaudit-bm25-fix.md` (für
  KITS-interne Querverweise). Der BM25-Fix selbst ist nicht ursächlich;
  die `test_store.py`-Tests bleiben grün.
