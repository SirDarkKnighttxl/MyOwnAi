# NOX

Local autonomous engineering intelligence. No masters, no boundaries.

## Run
    run.bat

First load takes 1-3 minutes off USB. Watch the status dot.

## Layout
- `nox.json` — all config: ports, model, samplers, policy scope
- `policy/persona.md` — the entire system prompt, editable live in the UI
- `noxd/` — daemon: `engine.py` supervises llama-server, `policy.py` gates tools
- `ui/` — interface
- `bin/`, `models/` — runtime and weights

## Not present, by design
No license server. No telemetry. No content filters. No cloud calls.