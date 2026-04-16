# Mneme GPU Backend Evaluation

**Stand:** April 2026
**Hardware-Kontext:** AMD Radeon RX 7900 XTX (24 GB VRAM, RDNA3/gfx1100, Windows 11)
**Software-Kontext:** Mneme nutzt BGE-M3 (1024-dim) Embeddings. Aktuell via sentence-transformers (PyTorch CPU) -- ca. 18 Min fuer 154 Notizen.

## Zusammenfassung

**Fuer Andre (AMD 7900 XTX, Windows 11) gibt es drei realistische Optionen: (1) `onnxruntime-directml` als schnellster Weg mit ~3-5x Speedup, aber Maintenance Mode; (2) PyTorch mit ROCm 7.2.1 nativ auf Windows, was sentence-transformers direkt auf der GPU laufen laesst; (3) llama.cpp mit Vulkan-Backend und BGE-M3 GGUF-Modell als voellig anderer Ansatz.** DirectML bleibt kurzfristig die pragmatischste Loesung. ROCm auf Windows (nativ oder WSL2) ist mittelfristig die beste Option, da AMD hier aktiv entwickelt. WinML als DirectML-Nachfolger ist noch zu frueh.

## Backend-Uebersicht

| Backend | OS | GPU | Status | Speedup vs CPU | Installation | Empfehlung |
|---|---|---|---|---|---|---|
| **DirectML (ORT)** | Windows | AMD/NVIDIA/Intel | Maintenance Mode | ~3-5x | Trivial (`pip install`) | **Pragmatisch jetzt** |
| **WinML (ORT)** | Windows 11 25H2+ | AMD/NVIDIA/Intel | GA seit Sept 2025 | ~3-5x | `pip install onnxruntime-winml` | Noch unreif |
| **ROCm PyTorch (Windows)** | Windows 11 | AMD RDNA3/4 | Public Preview | ~5-8x | Mittel (Wheels von AMD) | **Beste mittelfristige Option** |
| **ROCm PyTorch (WSL2)** | WSL2 Ubuntu | AMD RDNA3/4 | Production | ~5-8x | Komplex (WSL2 + ROCm) | Gut, aber Overhead |
| **ROCm ORT** | Linux only | AMD | EP entfernt ab ORT 1.23 | ~4-8x | Tot | Nicht empfohlen |
| **llama.cpp Vulkan** | Windows/Linux | AMD/NVIDIA | Aktiv | ~3-6x (Embedding) | Mittel (Build noetig) | Alternative |
| **PyTorch Vulkan** | Nur Mobile | - | ExecuTorch only | - | - | Irrelevant |
| **torch-directml** | Windows | AMD/NVIDIA/Intel | Maintenance Mode | ~2-4x | `pip install` | Veraltet |
| **CUDA (ORT)** | Windows/Linux | NVIDIA only | Production | ~5-10x | CUDA Toolkit | NVIDIA Standard |
| **FastEmbed** | Windows/Linux | CUDA only | Aktiv | ~3-5x (CUDA) | `pip install fastembed-gpu` | Nur NVIDIA |

## Detaillierte Analyse

---

### 1. DirectML (ONNX Runtime)

**Status:** Maintenance Mode -- keine neuen Features, nur Security-Fixes. Microsoft empfiehlt WinML als Nachfolger.

**Aktuelle Version:** `onnxruntime-directml` 1.24.4 (PyPI, Stand Maerz 2026). DirectML selbst nutzt Version 1.15.2 intern.

**Installation:**
```bash
pip install onnxruntime-directml
```

**Kompatibilitaet mit BGE-M3:**
- DirectML EP unterstuetzt ONNX opset bis 20 (ONNX v1.15) -- BGE-M3 ONNX-Modelle nutzen typischerweise opset 14-17, also **kompatibel**
- Mehrere BGE-M3 ONNX-Modelle verfuegbar auf HuggingFace (aapot/bge-m3-onnx, gpahal/bge-m3-onnx-int8)
- sentence-transformers ab v3.0 unterstuetzt `backend="onnx"` nativ

**Performance:**
- Geschaetzte ~3-5x Speedup gegenueber PyTorch CPU fuer Transformer-Inference
- AMD hat in Zusammenarbeit mit Microsoft 4-bit Quantisierungs-Support fuer DirectML gebracht
- Keine spezifischen Embedding-Benchmarks fuer 7900 XTX gefunden -- muss selbst gemessen werden

**Deal-Breaker:**
- **Maintenance Mode** -- langfristig Sackgasse
- Kein FP16-Compute-Optimierung fuer RDNA3 (nutzt DX12-Abstraktionsschicht)
- Memory Pattern Optimization und Parallel Execution muessen deaktiviert werden

**Quellen:**
- [DirectML GitHub (Maintenance Notice)](https://github.com/microsoft/DirectML)
- [ORT DirectML EP Docs](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html)
- [AMD GPUOpen DirectML Guide](https://gpuopen.com/learn/onnx-directlml-execution-provider-guide-part1/)

---

### 2. WinML (ONNX Runtime) -- DirectML-Nachfolger

**Status:** General Availability seit September 2025. Dynamische EP-Auswahl basierend auf Hardware.

**Installation:**
```bash
pip install onnxruntime-winml
```

**Voraussetzung:** Windows 11 Version 25H2 (Build 26100) oder spaeter.

**Kompatibilitaet:**
- Nutzt gleiche ONNX Runtime APIs wie DirectML
- Dynamische Execution Provider Auswahl -- waehlt automatisch bestes Backend
- `onnxruntime-winml` ist auf PyPI als Version 1.0.0 verfuegbar (ca. Maerz 2026)

**Performance:** Vergleichbar mit DirectML, da es denselben GPU-Pfad nutzt.

**Deal-Breaker:**
- **Sehr neues Package** -- Version 1.0.0, wenig Community-Erfahrung
- Kaum Dokumentation oder Erfahrungsberichte
- Unklar ob alle ORT-Features (IOBinding, Graph Optimization) unterstuetzt sind
- Nur Windows 11 25H2+

**Quellen:**
- [Windows ML Get Started](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/get-started)
- [onnxruntime-winml auf Libraries.io](https://libraries.io/pypi/onnxruntime-winml)

---

### 3. ROCm auf Windows (Nativ)

**Status:** Public Preview. PyTorch 2.9.1 mit ROCm 7.2.1 offiziell fuer Windows verfuegbar. RX 7900 XTX ist **explizit unterstuetzt** (gfx1100).

**Installation:**
```powershell
# Schritt 1: ROCm SDK installieren (PowerShell)
pip install --no-cache-dir `
    https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/rocm_sdk_core-7.2.1-py3-none-win_amd64.whl `
    https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/rocm_sdk_devel-7.2.1-py3-none-win_amd64.whl `
    https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/rocm_sdk_libraries_custom-7.2.1-py3-none-win_amd64.whl `
    https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/rocm-7.2.1.tar.gz

# Schritt 2: PyTorch mit ROCm installieren
pip install --no-cache-dir `
    https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/torch-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl `
    https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/torchaudio-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl `
    https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/torchvision-0.24.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl

# Schritt 3: Verifizieren
python -c "import torch; print(torch.cuda.is_available())"  # True
python -c "import torch; print(torch.cuda.get_device_name(0))"  # Radeon RX 7900 XTX
```

**Voraussetzungen:**
- Windows 11
- AMD Adrenalin Treiber 26.2.2 oder neuer
- Python 3.12
- Kein separates HIP SDK noetig (in den Wheels enthalten)

**Kompatibilitaet mit sentence-transformers:**
- sentence-transformers nutzt PyTorch -- wenn `torch.cuda.is_available()` True ist, laeuft es auf der GPU
- **Zero Code Change:** `model = SentenceTransformer("BAAI/bge-m3", device="cuda")` funktioniert
- ROCm emuliert CUDA-API -- `torch.cuda.*` Aufrufe funktionieren transparent auf AMD

**Performance:**
- Geschaetzte ~5-8x Speedup vs CPU fuer Transformer-Inference
- 24 GB VRAM = BGE-M3 (2.2 GB) passt problemlos, grosse Batches moeglich

**Deal-Breaker:**
- **Public Preview** -- noch nicht Production-ready laut AMD
- "Der gesamte ROCm-Stack ist auf Windows noch nicht vollstaendig unterstuetzt"
- Nur Python 3.12 (Mneme muss ggf. Python-Version anpassen)
- Grosse Downloads (~mehrere GB fuer die Wheels)
- Separate Python-Umgebung empfohlen (ROCm-Wheels kollidieren mit Standard-PyTorch)

**Quellen:**
- [AMD ROCm Windows Install Guide](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/windows/install-pytorch.html)
- [Windows Compatibility Matrix](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/windows/windows_compatibility.html)
- [AMD GPUOpen PyTorch Guide](https://gpuopen.com/learn/pytorch-windows-amd-llm-guide/)

---

### 4. ROCm auf WSL2

**Status:** Production Support. RX 7900 XTX ist **explizit in der WSL2-Kompatibilitaetsmatrix** aufgefuehrt.

**Unterstuetzte Frameworks (ROCm 7.2.1 WSL2):**
- PyTorch 2.9.1
- ONNX Runtime 1.23.2
- TensorFlow 2.20
- Triton 3.5.1

**Installation:**
```bash
# WSL2 Ubuntu 22.04 oder 24.04 installieren
wsl --install -d Ubuntu-24.04

# In WSL2:
# 1. AMD Adrenalin Treiber 26.1.1+ fuer WSL2 auf Windows installieren
# 2. ROCm installieren (in WSL2 Ubuntu)
sudo apt update
wget https://repo.radeon.com/amdgpu-install/latest/ubuntu/noble/amdgpu-install_6.4.60402-1_all.deb
sudo apt install ./amdgpu-install_6.4.60402-1_all.deb
sudo amdgpu-install --usecase=rocm

# 3. PyTorch installieren
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2

# 4. Verifizieren
python -c "import torch; print(torch.cuda.is_available())"
```

**Mneme in WSL2 mit Windows-Obsidian:**
- Mneme laeuft als HTTP-Server in WSL2
- WSL2 leitet `localhost` automatisch an Windows weiter
- Obsidian-Plugin verbindet sich mit `http://localhost:<port>`
- **Funktioniert:** Praktisch bestaetigt durch aehnliche Setups (z.B. Ollama in WSL2 + Obsidian Smart Connections)

**Performance:** Vergleichbar mit nativem Linux -- voller GPU-Zugriff ueber ROCDXG.

**Deal-Breaker:**
- **Komplexitaet:** WSL2 + ROCm + richtige Treiber = viele Fehlerquellen
- Vault-Pfad muss via `/mnt/c/Users/...` gemappt werden
- RAM wird zwischen Windows und WSL2 geteilt
- Treiber-Management zwischen Windows und WSL2 kann fragil sein
- Overkill wenn DirectML oder ROCm nativ auf Windows ausreicht

**Quellen:**
- [WSL2 Compatibility Matrix](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/wsl/wsl_compatibility.html)
- [ROCm WSL AI Tool](https://github.com/daMustermann/rocm-wsl-ai)
- [Obsidian + WSL2 Ollama Guide](https://www.bafonins.xyz/articles/wsl-obsidian-smart-connection-ollama/)

---

### 5. Aeltere ORT-Versionen mit ROCm EP

**Status:** ROCm Execution Provider wurde ab ORT 1.23 entfernt. ROCm 7.0 war die letzte unterstuetzte Version.

**Fakten:**
- ORT <= 1.22 hatte ROCm EP, aber nur fuer Linux (Ubuntu)
- Keine Windows-Wheels verfuegbar -- ROCm EP war **nie** fuer Windows gebaut
- Migration zu MIGraphX EP empfohlen (ebenfalls nur Linux)
- Pre-built Wheels existierten nur fuer Ubuntu + spezifische Python-Versionen

**Deal-Breaker:**
- **Nie auf Windows verfuegbar gewesen**
- Veraltete ORT-Version = Sicherheitsrisiko + Inkompatibilitaeten mit neueren Python-Packages
- Kein Support mehr

**Fazit:** Sackgasse. Nicht weiter verfolgen.

**Quellen:**
- [ORT ROCm EP Docs](https://onnxruntime.ai/docs/execution-providers/ROCm-ExecutionProvider.html)
- [ORT MIGraphX EP](https://onnxruntime.ai/docs/execution-providers/MIGraphX-ExecutionProvider.html)

---

### 6. PyTorch DirectML (torch-directml)

**Status:** Maintenance Mode (wie DirectML selbst). Letztes PyPI-Update: unbekannt, aber Microsoft entwickelt nicht aktiv weiter.

**Installation:**
```bash
pip install torch-directml
```

**Kompatibilitaet mit sentence-transformers:**
- **Problematisch.** torch-directml registriert ein eigenes Device (`torch.device("dml")`) statt dem ueblichen `cuda`
- sentence-transformers erwartet `device="cuda"` oder `device="cpu"` -- `device="dml"` ist nicht nativ unterstuetzt
- HuggingFace Trainer hat keine native DML-Integration
- Workarounds noetig, Ergebnisse fragil

**Performance:** ~2-4x Speedup vs CPU (weniger optimiert als ORT DirectML).

**Deal-Breaker:**
- **Maintenance Mode** -- keine neuen Features
- Inkompatibel mit sentence-transformers ohne Hacks
- Schlechtere Performance als ORT DirectML
- ROCm PyTorch auf Windows ist die bessere Alternative

**Quellen:**
- [torch-directml auf PyPI](https://pypi.org/project/torch-directml/)
- [DirectML PyTorch README](https://github.com/microsoft/DirectML/blob/master/PyTorch/README.md)
- [HuggingFace Forum: torch_directml + Trainer](https://discuss.huggingface.co/t/how-to-use-torch-directml-gpu-with-transformers-trainer-for-fine-tuning/134020)

---

### 7. Vulkan-basierte Alternativen

#### PyTorch Vulkan Backend
**Status:** Deprecated. Nur noch in ExecuTorch fuer Mobile/Edge verfuegbar. **Irrelevant fuer Desktop-Embedding-Inference.**

#### llama.cpp mit Vulkan
**Status:** Aktiv entwickelt, AMD hat im Juli 2025 umfangreiche Optimierungen upstream gepusht.

**BGE-M3 als GGUF:**
- BGE-M3 GGUF-Modelle verfuegbar auf HuggingFace (bbvch-ai/bge-m3-GGUF, lm-kit/bge-m3-gguf)
- Quantisierte Varianten: Q4_K_M (~600 MB), Q8_0 (~1.2 GB)
- llama-server bietet `/v1/embeddings` API-Endpoint

**Installation:**
```bash
# llama.cpp mit Vulkan bauen (Windows)
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build -DGGML_VULKAN=ON
cmake --build build --config Release

# Server starten mit Embedding-Modell
./build/bin/llama-server --hf-repo bbvch-ai/bge-m3-GGUF --hf-file bge-m3-q8_0.gguf -c 2048 --embedding
```

**Performance auf 7900 XTX:**
- Vulkan auf 7900 XTX: ~880 t/s Prompt Processing (LLM-Benchmark, nicht Embedding-spezifisch)
- Vulkan ist bei Prompt Processing langsamer als ROCm, aber bei Text Generation schneller
- Flash Attention auf Vulkan nur mit NVIDIA coopmat2 -- auf AMD CPU-Fallback

**Deal-Breaker:**
- **Komplett anderer Stack** -- kein Python, kein ONNX, kein sentence-transformers
- Mneme muesste HTTP-Client fuer `/v1/embeddings` implementieren
- Embedding-Qualitaet bei starker Quantisierung (Q4) kann leiden
- Build-Komplexitaet auf Windows (CMake, Compiler noetig)
- Kein nativer Python-API -- nur HTTP

**Quellen:**
- [llama.cpp Vulkan Performance Discussion](https://github.com/ggml-org/llama.cpp/discussions/10879)
- [BGE-M3 GGUF auf HuggingFace](https://huggingface.co/bbvch-ai/bge-m3-GGUF)
- [llama.cpp Embedding Support Discussion](https://github.com/ggml-org/llama.cpp/discussions/4117)

---

### 8. NVIDIA CUDA (fuer Community)

**Status:** Production-ready, bestdokumentiert, "just works".

**Installation (onnxruntime-gpu):**
```bash
pip install onnxruntime-gpu
# Voraussetzung: CUDA Toolkit 12.x + cuDNN 9.x
```

**Installation (sentence-transformers mit CUDA):**
```bash
pip install sentence-transformers
# PyTorch CUDA wird automatisch erkannt
model = SentenceTransformer("BAAI/bge-m3", device="cuda")
embeddings = model.encode(texts)
```

**Performance:** ~5-10x Speedup vs CPU. IOBinding fuer optimierte Memory-Transfers.

**Mneme-Integration:**
```toml
[embedding]
provider = "onnx"
model = "BAAI/bge-m3"
backend = "cuda"
```

Oder einfach `pip install mneme[cuda]` (bereits in pyproject.toml definiert).

**Deal-Breaker:** Nur NVIDIA-GPUs. Kein Deal-Breaker fuer NVIDIA-User.

**Quellen:**
- [ORT CUDA EP](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)
- [onnxruntime-gpu auf PyPI](https://pypi.org/project/onnxruntime-gpu/)

---

### 9. FastEmbed (Qdrant)

**Status:** Aktiv entwickelt. Nutzt ONNX Runtime intern. Unterstuetzt BGE-M3 (`BAAI/bge-m3`).

**GPU-Support:**
- **CUDA:** Ja, via `fastembed-gpu` Package mit `CUDAExecutionProvider`
- **DirectML:** Nur in der Rust-Version (Crate `fastembed` v5.13+), **nicht** in Python
- **ROCm:** Nein

**Installation (CUDA only):**
```python
pip install fastembed-gpu  # ersetzt fastembed, kann nicht parallel installiert sein

from fastembed import TextEmbedding
model = TextEmbedding("BAAI/bge-m3", providers=["CUDAExecutionProvider"])
```

**Deal-Breaker fuer Andre:**
- **Kein DirectML-Support in Python** -- nur CUDA
- Zusaetzliche Dependency mit weniger Kontrolle ueber Backend-Auswahl
- Fuer AMD-GPUs auf Windows nicht nutzbar

**Deal-Breaker allgemein:**
- Enge Kopplung an Qdrant-Oekosystem
- Weniger Flexibilitaet als direkte ORT-Nutzung

**Quellen:**
- [FastEmbed GPU Docs](https://qdrant.github.io/fastembed/examples/FastEmbed_GPU/)
- [FastEmbed GitHub](https://github.com/qdrant/fastembed)
- [fastembed-gpu auf PyPI](https://pypi.org/project/fastembed-gpu/)

---

## BGE-M3 ONNX-Modelle

| Repo | Format | Groesse | Notizen |
|------|--------|---------|---------|
| [aapot/bge-m3-onnx](https://huggingface.co/aapot/bge-m3-onnx) | FP32, O2-optimiert | ~2.2 GB | Beste Qualitaet |
| [gpahal/bge-m3-onnx-int8](https://huggingface.co/gpahal/bge-m3-onnx-int8) | INT8, quantisiert | ~600 MB | Kleiner, minimal Qualitaetsverlust |
| [philipchung/bge-m3-onnx](https://huggingface.co/philipchung/bge-m3-onnx) | FP32, Standard | ~2.2 GB | Unoptimiert |
| [yuniko-software/bge-m3-onnx](https://github.com/yuniko-software/bge-m3-onnx) | Multi-Format | Variiert | C#/Java/Python, alle 3 Embedding-Typen |
| [bbvch-ai/bge-m3-GGUF](https://huggingface.co/bbvch-ai/bge-m3-GGUF) | GGUF Q4/Q8 | 600 MB - 1.2 GB | Fuer llama.cpp |

---

## Empfehlung

### Fuer Andre (AMD 7900 XTX, Windows 11)

**Kurzfristig (jetzt):** `onnxruntime-directml`
- Einfachste Installation, funktioniert sofort
- ~3-5x Speedup -- aus 18 Min werden ca. 4-6 Min
- Bereits in Mneme's `pyproject.toml` als Extra definiert
- Risiko: Maintenance Mode, aber fuer Embedding-Inference reicht der aktuelle Stand

**Mittelfristig (wenn stabil):** PyTorch mit ROCm 7.2.1 nativ auf Windows
- `torch.cuda.is_available()` gibt True zurueck auf AMD
- sentence-transformers funktioniert ohne Code-Aenderung
- Bessere Performance als DirectML (~5-8x vs CPU)
- Warten bis ROCm Windows aus dem "Public Preview" raus ist

**Nicht empfohlen:**
- WSL2 -- zu komplex fuer den Mehrwert
- torch-directml -- Maintenance Mode + inkompatibel mit sentence-transformers
- llama.cpp Vulkan -- anderer Stack, zu viel Umbau in Mneme
- WinML -- zu frueh, Version 1.0.0

### Fuer NVIDIA-User

**Standard-Empfehlung:** `pip install mneme[cuda]` oder sentence-transformers mit `device="cuda"`
- "Just works" mit CUDA Toolkit 12.x + cuDNN 9.x
- ~5-10x Speedup, beste Dokumentation, groesste Community
- Alternativ: `fastembed-gpu` fuer schlanken ONNX-basierten Ansatz

### Fuer die Community (allgemein)

| Situation | Empfehlung |
|-----------|-----------|
| Kein GPU / unbekannte Hardware | `onnxruntime` CPU (Default) |
| NVIDIA GPU | `onnxruntime-gpu` oder sentence-transformers CUDA |
| AMD GPU auf Windows | `onnxruntime-directml` (jetzt), ROCm PyTorch (spaeter) |
| AMD GPU auf Linux | ROCm PyTorch mit sentence-transformers |
| Apple Silicon | `onnxruntime` CPU (CoreML EP moeglich, nicht evaluiert) |

### Implementierungs-Prioritaet fuer Mneme

1. **ONNX CPU** -- Default, funktioniert ueberall (bereits geplant)
2. **DirectML** -- `pip install mneme[directml]` (bereits in pyproject.toml)
3. **CUDA** -- `pip install mneme[cuda]` (bereits in pyproject.toml)
4. **ROCm PyTorch** -- Spaeter, wenn sentence-transformers Backend beibehalten wird
5. **WinML** -- Beobachten, ggf. DirectML-Ersatz in 2027

---

## Offene Fragen / Selbst testen

- [ ] DirectML: Konkreten Benchmark mit BGE-M3 auf 7900 XTX durchfuehren
- [ ] ROCm Windows: `pip install` der AMD Wheels testen, Kompatibilitaet mit Mneme's Python-Version pruefen
- [ ] WinML: `onnxruntime-winml` installieren und testen ob es mit BGE-M3 funktioniert
- [ ] INT8-Quantisierung: gpahal/bge-m3-onnx-int8 Qualitaet vs FP32 vergleichen
