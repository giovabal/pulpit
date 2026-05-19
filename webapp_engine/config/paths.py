from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

CONFIG_DIR = BASE_DIR / "configuration"
ENV_PATH = CONFIG_DIR / ".env"
CRAWL_PATH = CONFIG_DIR / ".operations-crawl"
STRUCTURAL_PATH = CONFIG_DIR / ".operations-structural"

SYSTEM_PATH = BASE_DIR / ".system"
