"""Paths and config loading."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
SYMBOLS_DIR = DATA_DIR / "symbols"
QUESTIONS_CSV = DATA_DIR / "questions.csv"
QUESTION_PNG_DIR = DATA_DIR / "questions"
STIMULI_DIR = ROOT / "stimuli"
MANIFEST = STIMULI_DIR / "manifest.csv"
CACHE_DIR = ROOT / "cache"
RESULTS_DIR = ROOT / "results"
CONFIG_PATH = ROOT / "config.yaml"
SMOKE_STATUS = CACHE_DIR / "smoke_status.json"


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    cfg["_config_path"] = str(path)  # so the run folder snapshots the file actually used
    return cfg


def questions_path(cfg: dict) -> Path:
    """Active statement file (config `questions_file`, default data/questions.csv)."""
    path = ROOT / cfg.get("questions_file", "data/questions.csv")
    if not path.exists():
        raise SystemExit(f"{path.relative_to(ROOT)} not found. Run `python -m vcb screen` first.")
    return path


def latest_run_dir() -> Path:
    """Newest real run folder (excludes _mock)."""
    # Only main logprob runs (they have scores.csv); excludes _mock and the awareness/ and reasoning/ folders.
    runs = sorted(p for p in RESULTS_DIR.glob("*") if p.is_dir() and not p.name.startswith("_")
                  and (p / "scores.csv").exists())
    if not runs:
        raise SystemExit("No runs found under results/. Run `python -m vcb run` first.")
    return runs[-1]


def resolve_run_dir(run_id: str | None) -> Path:
    return RESULTS_DIR / run_id if run_id else latest_run_dir()


def stimuli_dir(cfg: dict) -> Path:
    """Stimulus folder for this config (default stimuli/; other layouts get their own folder)."""
    return ROOT / cfg.get("stimuli_dir", "stimuli")


def manifest_path(cfg: dict) -> Path:
    return stimuli_dir(cfg) / "manifest.csv"
