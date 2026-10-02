"""Inicia a interface: `kentor ui` ou `python scripts/run_ui.py` (funciona no Windows)."""
from __future__ import annotations

import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from ..config import PROJECT_ROOT

APP = Path(__file__).resolve().parent / "streamlit_app.py"


def _open_when_ready(url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/_stcore/health", timeout=2) as r:
                if r.status == 200:
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.5)


def launch(port: int = 8501, open_browser: bool = True) -> int:
    url = f"http://localhost:{port}"
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(APP),
        "--server.port", str(port),
        "--server.headless", "true",
        "--server.address", "localhost",  # só este computador acessa (a tela permite escolher "Sócio")
        "--browser.gatherUsageStats", "false",
    ]
    print(f"Kentor Memória: iniciando a interface em {url}  (Ctrl+C para encerrar)", flush=True)
    if open_browser:
        threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()
    try:
        # cwd = raiz do projeto: o Streamlit lê .streamlit/config.toml (tema) de lá
        return subprocess.call(cmd, cwd=str(PROJECT_ROOT))
    except KeyboardInterrupt:
        return 0
