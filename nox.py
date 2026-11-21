"""NOX desktop shell."""
import json
import pathlib
import socket
import threading
import time

import uvicorn
import webview

ROOT = pathlib.Path(__file__).resolve().parent
HOST = "127.0.0.1"


def free_port(start: int) -> int:
    for port in range(start, start + 200):
        with socket.socket() as s:
            if s.connect_ex((HOST, port)) != 0:
                return port
    raise RuntimeError("no free port")


def serve(port: int) -> None:
    uvicorn.run("noxd.main:app", host=HOST, port=port, log_level="warning")


def wait(port: int) -> None:
    for _ in range(160):
        with socket.socket() as s:
            if s.connect_ex((HOST, port)) == 0:
                return
        time.sleep(0.25)


if __name__ == "__main__":
    ui_port = free_port(8080)
    engine_port = free_port(8081)
    (ROOT / "runtime.json").write_text(
        json.dumps({"port": ui_port, "engine_port": engine_port}), encoding="utf-8"
    )
    threading.Thread(target=serve, args=(ui_port,), daemon=True).start()
    wait(ui_port)
    webview.create_window(
        "NOX", f"http://{HOST}:{ui_port}",
        width=1320, height=880, background_color="#0a0a12",
    )
    webview.start()
