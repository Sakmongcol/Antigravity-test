"""Render/Gunicorn entrypoint for the LINE bot app."""

import importlib.util
from pathlib import Path


module_path = Path(__file__).with_name("line-bot.py")
spec = importlib.util.spec_from_file_location("line_bot_app", module_path)
line_bot_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(line_bot_app)

app = line_bot_app.app
