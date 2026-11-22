# NOX

Local autonomous engineering intelligence. No masters, no boundaries.

## Run
    run.bat

First load takes 1-3 minutes off USB. Watch the status dot.

`run.bat` uses `runtime\python\python.exe` when it exists. Otherwise it falls back to a `python` on PATH. If neither works, it prints an error and stops.

## Portable runtime (one-time setup)
    setup_runtime.bat

This downloads the official `python-3.12.10-embed-amd64.zip` from python.org and checks its pinned SHA-256. It unpacks the zip into `runtime\python` and installs `packaging\python312._pth`, which puts the project root (`..\..`) on `sys.path` and enables `site`. It then bootstraps pip with `get-pip.py` and installs `requirements.txt` (fastapi, uvicorn, httpx, pywebview). This is the only step that uses the network. NOX makes no network calls at runtime. `runtime/` is gitignored.

The embeddable distro has no tkinter, venv or ensurepip, and NOX uses none of them. It ignores `PYTHONPATH` whenever a `._pth` file exists, so the `._pth` file is what makes `noxd` importable.

Offline alternative: copy a finished `runtime\python` folder from another NOX machine into this repo's `runtime\`. Every path in it is relative, so it works from any drive letter.

### Acceptance: start with Python stripped from PATH
In a new `cmd` window at the repo root:

    set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\WindowsPowerShell\v1.0"
    where python
    run.bat

`where python` must report that it found nothing. NOX must still start, and the window must not print `[NOX] runtime\python not found; using python from PATH.` Without `runtime\python`, the same window must print `[NOX] No Python found.` and stop.

## Layout
- `nox.json` — all config: ports, model, samplers, policy scope
- `policy/persona.md` — the entire system prompt, editable live in the UI
- `noxd/` — daemon: `engine.py` supervises llama-server, `policy.py` gates tools
- `ui/` — interface
- `bin/`, `models/` — runtime and weights
- `runtime/python/` — portable embedded Python (made by `setup_runtime.bat`, not committed)
- `packaging/python312._pth` — template that `setup_runtime.bat` copies into the runtime
- `requirements.txt` — daemon deps only; training deps are in `train/requirements.txt`

## Not present, by design
No license server. No telemetry. No content filters. No cloud calls.