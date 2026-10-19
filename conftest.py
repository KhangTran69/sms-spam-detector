"""Make project-root imports (src, api) work for bare `pytest` runs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
