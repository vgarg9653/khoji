"""Load .env into the environment.

Imported first by every entry point. Secrets live in a git-ignored .env locally;
in production Cloud Run injects them from Secret Manager and there is no .env to
find, so this is a no-op there. Real environment variables always win, which is
what makes the same code work in both places.
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv
        # override=False: a real env var (Cloud Run, CI) beats the local file.
        load_dotenv(env_file, override=False)
    except ImportError:
        # Tiny fallback so the bot still starts without python-dotenv.
        import os
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.split(" #")[0].strip().strip("'\"")
            if k.strip() and v and k.strip() not in os.environ:
                os.environ[k.strip()] = v
