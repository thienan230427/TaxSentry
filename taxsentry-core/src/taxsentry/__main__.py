"""
Main entry point for TaxSentry AI Agent.
Allows running with: python -m taxsentry
"""
import sys
import os

# Ensure the package is importable even if not installed
if __name__ == "__main__" and __package__ is None:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

# Bootstrap virtual environment if not already in one (legacy support)
in_venv = (sys.prefix != sys.base_prefix) or ('VIRTUAL_ENV' in os.environ)
if not in_venv:
    import subprocess
    import sys
    root_dir = Path(__file__).parent.parent.parent.parent
    venv_python = root_dir / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        venv_python = root_dir / ".venv" / "bin" / "python"
    
    if venv_python.exists():
        args = [str(venv_python), "-m", "taxsentry"] + sys.argv[1:]
        try:
            sys.exit(subprocess.run(args).returncode)
        except Exception as e:
            print(f"Không thể tự động chuyển hướng sang môi trường ảo: {e}")
            sys.exit(1)

# Import and run the TUI
from taxsentry.ui.tui import main

if __name__ == "__main__":
    main()
