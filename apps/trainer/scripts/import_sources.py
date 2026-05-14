#!/usr/bin/env python3
"""
Import data sources into apps/trainer/data/raw/.
Copies/converts from various source directories.
"""

import shutil
import sys
from pathlib import Path

TRAINER_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = TRAINER_DIR / "data" / "raw"

# Source paths
DOCS_DIR = Path("/home/chaos/proyectos/docs")
KATETO_DIR = Path("/home/chaos/proyectos/kateto")
CLASSIFIER_DATA = KATETO_DIR / "apps/classifier/data"
XAVIER_HTML = KATETO_DIR / "Xavier_ Renegade Angel - Wikiquote.html"


def import_convos():
    """Import OpenCode conversation logs."""
    src = DOCS_DIR / "convos"
    dst = RAW_DIR / "convos"
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    if src.exists():
        for f in sorted(src.glob("*.json")):
            shutil.copy2(f, dst / f.name)
            count += 1
    print(f"  Imported {count} conversation files")
    return count


def import_training_datasets():
    """Import existing kateto training datasets."""
    src = DOCS_DIR / ".training"
    dst = RAW_DIR / "training"
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    if src.exists():
        for f in src.glob("kateto_dataset_*.json"):
            shutil.copy2(f, dst / f.name)
            count += 1
        # Also copy filtered/cleaned datasets
        for f in src.glob("*filtered*.json"):
            shutil.copy2(f, dst / f.name)
            count += 1
    print(f"  Imported {count} training dataset files")
    return count


def import_blogs():
    """Import blog posts (user's writing style)."""
    src = DOCS_DIR / "blogs"
    dst = RAW_DIR / "blogs"
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    if src.exists():
        for f in sorted(src.glob("*.md")):
            if not f.name.startswith("."):
                shutil.copy2(f, dst / f.name)
                count += 1
    print(f"  Imported {count} blog posts")
    return count


def import_cv():
    """Import user's CV."""
    src = DOCS_DIR / "Currículum.txt"
    dst = RAW_DIR / "cv.txt"
    if src.exists():
        shutil.copy2(src, dst)
        print(f"  Imported CV: {src.name}")
        return 1
    return 0


def import_classifier_data():
    """Import classifier training data and history."""
    dst = RAW_DIR / "classifier"
    dst.mkdir(parents=True, exist_ok=True)
    history_dst = dst / "history"
    history_dst.mkdir(parents=True, exist_ok=True)
    count = 0

    if CLASSIFIER_DATA.exists():
        # Training CSVs
        for f in CLASSIFIER_DATA.glob("*.csv"):
            shutil.copy2(f, dst / f.name)
            count += 1
        # History JSONs
        for f in CLASSIFIER_DATA.glob("*.json"):
            if f.is_file():
                shutil.copy2(f, history_dst / f.name)
                count += 1

    print(f"  Imported {count} classifier data files")
    return count


def import_xavier_quotes():
    """Import Xavier Wikiquote HTML."""
    dst = RAW_DIR / "xavier.html"
    if XAVIER_HTML.exists():
        shutil.copy2(XAVIER_HTML, dst)
        print(f"  Imported Xavier Wikiquote")
        return 1
    print("  \u26a0 Xavier Wikiquote not found")
    return 0


def main():
    print("Importing data sources into apps/trainer/data/raw/...")
    print()

    results = {
        "convos": import_convos(),
        "training_datasets": import_training_datasets(),
        "blogs": import_blogs(),
        "cv": import_cv(),
        "classifier_data": import_classifier_data(),
        "xavier_quotes": import_xavier_quotes(),
    }

    total = sum(results.values())
    print(f"\nDone! Imported {total} items total.")
    print(f"\nBreakdown:")
    for key, val in results.items():
        print(f"  {key}: {val}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
