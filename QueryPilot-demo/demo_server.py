"""Start the standalone demo (API + Chat UI) and open the browser."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

HOST = "127.0.0.1"
PORT = 8787


def _port_free(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((HOST, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _is_our_demo(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/", timeout=0.8) as resp:
            ctype = (resp.headers.get("content-type") or "").lower()
            body = resp.read(200).decode("utf-8", errors="ignore")
            return resp.status == 200 and "html" in ctype and "QueryPilot" in body
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _open_browser(port: int) -> None:
    url = f"http://{HOST}:{port}/"
    time.sleep(0.8)
    webbrowser.open(url)


def main() -> int:
    env = ROOT / ".env"
    example = ROOT / ".env.example"
    if not env.exists() and example.exists():
        env.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")

    url = f"http://{HOST}:{PORT}/"
    if _is_our_demo(PORT):
        print(f"Demo already running: {url}", flush=True)
        webbrowser.open(url)
        return 0

    if not _port_free(PORT):
        print(f"Port {PORT} is in use but is not QueryPilot Demo.", flush=True)
        print("Close the other program, then run 启动演示.bat again.", flush=True)
        input("Press Enter to exit...")
        return 1

    print(f"QueryPilot Demo  http://{HOST}:{PORT}/", flush=True)
    print("Keep this window open. Close it to stop the demo.", flush=True)

    from querypilot.api.app import create_app
    import uvicorn

    threading.Thread(target=_open_browser, args=(PORT,), daemon=True).start()
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
