import os
import sys
from pathlib import Path

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
