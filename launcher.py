"""PyInstaller entry point.

PyInstaller wants a script, not a module; this is `python -m pyscope` as a
file. Nothing else should import it.
"""
import multiprocessing
import sys

from pyscope.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
