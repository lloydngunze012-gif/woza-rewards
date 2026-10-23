from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Safe local defaults only. Set real values in the environment for deploy.
SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-woza-secret-change-me"
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD") or "woza-demo"
