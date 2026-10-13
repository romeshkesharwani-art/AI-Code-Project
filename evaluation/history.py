import json
import os
import tempfile
from pathlib import Path
from typing import Any


HISTORY_PATH = Path(__file__).resolve().parent / "results" / "runs.json"


def load_runs(path: Path = HISTORY_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as history_file:
        runs = json.load(history_file)
    if not isinstance(runs, list) or any(not isinstance(run, dict) for run in runs):
        raise ValueError(f"Evaluation history at {path} must contain a JSON array of runs.")
    return runs


def save_run(run: dict[str, Any], path: Path = HISTORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    runs = load_runs(path)
    runs.insert(0, run)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
            suffix=".tmp",
        ) as history_file:
            temporary_path = history_file.name
            json.dump(runs, history_file, ensure_ascii=False, indent=2)
            history_file.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
