"""Abre a interface gráfica. Uso (Windows/macOS/Linux): python scripts/run_ui.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kentor_memoria.ui.launcher import launch  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(launch(open_browser="--no-browser" not in sys.argv))
