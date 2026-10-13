"""Central configuration."""

import os
from pathlib import Path

ROOT = Path(__file__).parent
INVOICE_DIR = ROOT / "data" / "invoices"
RUNS_DIR = ROOT / "runs"
DB_PATH = ROOT / "company_app" / "payables.db"

APP_HOST = "127.0.0.1"
APP_PORT = int(os.getenv("APP_PORT", "5055"))
APP_URL = f"http://{APP_HOST}:{APP_PORT}"

APPROVAL_THRESHOLD = 10_000.00  # amounts above this need human approval
MAX_STEPS = 40  # hard cap on agent loop iterations
MAX_RETRIES_PER_TOOL = 3  # after this the agent must stop/ask instead of retrying
MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-5-5")

# Local LLM (Apple Silicon, mlx-lm) used by --brain mlx
MLX_MODEL = os.getenv("MLX_MODEL", "mlx-community/Mistral-7B-Instruct-v0.2-4bit")
MLX_MAX_TOKENS = int(os.getenv("MLX_MAX_TOKENS", "512"))
MLX_TEMPERATURE = float(os.getenv("MLX_TEMPERATURE", "0.0"))
