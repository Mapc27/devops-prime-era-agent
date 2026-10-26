import os
import sys
from pathlib import Path

os.environ.setdefault("OPSCREW_TRACING", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lab/executor"))
