#!/usr/bin/env python3
"""Remove all __pycache__ directories and .pyc/.pyo files."""

import shutil
import sys
from pathlib import Path


def clean_pycache(root: str = ".") -> None:
    root_path = Path(root).resolve()
    print(f"Cleaning Python cache files in: {root_path}\n")

    dir_count = 0
    file_count = 0

    # Remove __pycache__ directories
    for d in sorted(root_path.rglob("__pycache__")):
        if d.is_dir():
            print(f"  Removing dir:  {d}")
            shutil.rmtree(d)
            dir_count += 1

    # Remove stray .pyc / .pyo files outside __pycache__
    for pattern in ("*.pyc", "*.pyo"):
        for f in sorted(root_path.rglob(pattern)):
            if f.is_file():
                print(f"  Removing file: {f}")
                f.unlink()
                file_count += 1

    print(f"\nRemoved {dir_count} __pycache__ directories")
    print(f"Removed {file_count} .pyc/.pyo files")
    print("Done!")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    clean_pycache(target)