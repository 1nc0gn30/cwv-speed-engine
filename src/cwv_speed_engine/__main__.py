"""
Module execution entrypoint for cwv_speed_engine.

Usage:
  python -m cwv_speed_engine [subcommand]
"""

import sys
from cwv_speed_engine.cli import main

if __name__ == "__main__":
    sys.exit(main())
