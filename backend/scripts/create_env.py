"""Create .env from .env.example with new random secrets. An existing .env is never changed."""
from __future__ import annotations

import base64
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    target = ROOT / ".env"
    if target.exists():
        print("Keeping your existing .env file.")
        return
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    text = text.replace("SECRET_KEY=change-me", f"SECRET_KEY={secrets.token_urlsafe(48)}")
    text = text.replace("ENCRYPTION_KEY=change-me", f"ENCRYPTION_KEY={base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}")
    target.write_text(text, encoding="utf-8")
    print("Created .env with new random secrets.")


if __name__ == "__main__":
    main()
