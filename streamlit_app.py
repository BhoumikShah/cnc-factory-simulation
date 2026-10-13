from pathlib import Path
import runpy
import sys

# Ensure src/ is on Python search path
SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Launch main Streamlit application
runpy.run_path(str(SRC_DIR / "vmc_twin" / "ui" / "app.py"), run_name="__main__")
