from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.review import repository


def main() -> int:
    session = SessionLocal()
    try:
        repository.ensure_review_schema(session)
    finally:
        session.close()
    print("Review schema migration applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
