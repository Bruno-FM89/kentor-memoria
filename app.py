"""Atalho: `streamlit run app.py` (equivalente a `kentor ui`)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kentor_memoria.ui.app import render  # noqa: E402

render()
