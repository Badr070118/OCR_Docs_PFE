from __future__ import annotations

import json
from pathlib import Path
import sys

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.review import repository

SUPPLIERS = [
    {
        "canonical_name": "Attijariwafa bank",
        "ice": "001638957000074",
        "address": "2 Boulevard Moulay Youssef, Casablanca",
        "aliases": ["Attijariwafa bnak", "Attijari wafa bank", "Attijariwafa"],
    },
    {
        "canonical_name": "BMCE Bank",
        "ice": "001524119000048",
        "address": "140 Avenue Hassan II, Casablanca",
        "aliases": ["BMCF Bank", "BMCE Bnak", "Bank of Africa BMCE"],
    },
    {
        "canonical_name": "Maroc Telecom",
        "ice": "000056789000012",
        "address": "Avenue Annakhil, Rabat",
        "aliases": ["Maroc telekom", "MarocTelecom", "IAM Maroc Telecom"],
    },
]

CITIES = [
    {"canonical_name": "Casablanca", "aliases": ["Casablanka", "Casa blanca", "CasabIanca"]},
    {"canonical_name": "Rabat", "aliases": ["Rabbat", "Rabatt"]},
    {"canonical_name": "Marrakech", "aliases": ["Marrackech", "Marakech", "Marrakesh"]},
]

COUNTRIES = [
    {"canonical_name": "Morocco", "aliases": ["Maroc", "Moroco", "Morroco"]},
    {"canonical_name": "France", "aliases": ["Frnace", "Franec"]},
    {"canonical_name": "Spain", "aliases": ["Espagne", "Spian"]},
]


def seed_suppliers() -> int:
    session = SessionLocal()
    inserted = 0
    try:
        repository.ensure_review_schema(session)

        for supplier in SUPPLIERS:
            session.execute(
                text(
                    """
                    INSERT INTO suppliers (canonical_name, ice, address, aliases)
                    VALUES (:canonical_name, :ice, :address, CAST(:aliases AS JSONB))
                    ON CONFLICT (canonical_name)
                    DO UPDATE SET
                        ice = EXCLUDED.ice,
                        address = EXCLUDED.address,
                        aliases = EXCLUDED.aliases
                    """
                ),
                {
                    "canonical_name": supplier["canonical_name"],
                    "ice": supplier.get("ice"),
                    "address": supplier.get("address"),
                    "aliases": json.dumps(supplier.get("aliases") or []),
                },
            )
            inserted += 1

        for city in CITIES:
            session.execute(
                text(
                    """
                    INSERT INTO cities (canonical_name, aliases)
                    VALUES (:canonical_name, CAST(:aliases AS JSONB))
                    ON CONFLICT (canonical_name)
                    DO UPDATE SET aliases = EXCLUDED.aliases
                    """
                ),
                {
                    "canonical_name": city["canonical_name"],
                    "aliases": json.dumps(city.get("aliases") or []),
                },
            )
            inserted += 1

        for country in COUNTRIES:
            session.execute(
                text(
                    """
                    INSERT INTO countries (canonical_name, aliases)
                    VALUES (:canonical_name, CAST(:aliases AS JSONB))
                    ON CONFLICT (canonical_name)
                    DO UPDATE SET aliases = EXCLUDED.aliases
                    """
                ),
                {
                    "canonical_name": country["canonical_name"],
                    "aliases": json.dumps(country.get("aliases") or []),
                },
            )
            inserted += 1

        session.commit()
        return inserted
    finally:
        session.close()


def main() -> int:
    count = seed_suppliers()
    print(f"Seed completed: {count} reference entities upserted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
