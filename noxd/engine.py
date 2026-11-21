"""llama-server process supervisor."""
from __future__ import annotations

import pathlib
import socket
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
BIN = ROOT / "bin" / ("llama-server.exe" if sys.platform == "win32" else "llama-server")
LOG = ROOT / "logs" / "engine.log"


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.25)
        return s.connect_ex(("127.0.0.1", port)) == 0


class Engine:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.proc: subprocess.Popen | None = None
        self.port = cfg["server"]["engine_port"]
        self.error: str | None = None
        self.model_path: str | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def ready(self) -> bool:
        return self.running and _port_open(self.port)

    def resolve_model(self) -> pathlib.Path | None:
        for raw in self.cfg["model"].get("paths", []):
            p = pathlib.Path(raw)
            if not p.is_absolute():
                p = ROOT / p
            if p.exists():
                return p
        return None

    def log_tail(self, lines: int = 12) -> str:
        if not LOG.exists():
            return ""
        try:
            return "\n".join(LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
        except OSError:
            return ""

    def start(self) -> None:
        if self.ready:
            return
        self.stop()
        self.error = None

        model = self.resolve_model()
        if model is None:
            self.error = "no model found in any configured path"
            return
        if not BIN.exists():
            self.error = f"binary missing: {BIN}"
            return

        self.model_path = str(model)
        m = self.cfg["model"]
        args = [
            str(BIN),
            "-m", str(model),
            "-c", str(m["ctx"]),
            "-ngl", str(m["gpu_layers"]),
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "--jinja",
            "-np", "1",
        ]
        if m.get("no_mmap"):
            args.extend(["--load-mode", "none"])
        args.extend(m.get("extra_args", []))

        LOG.parent.mkdir(parents=True, exist_ok=True)
        handle = LOG.open("w", encoding="utf-8", errors="replace")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self.proc = subprocess.Popen(
                args, cwd=str(BIN.parent),
                stdout=handle, stderr=subprocess.STDOUT,
                creationflags=flags,
            )
        except OSError as exc:
            self.error = str(exc)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def wait_ready(self, timeout: float = 240.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.ready:
                return True
            if self.proc is not None and self.proc.poll() is not None:
                tail = self.log_tail(4)
                self.error = f"engine exit {self.proc.returncode}: {tail}"[-400:]
                return False
            time.sleep(1.0)
        self.error = "engine startup timeout"
        return False
