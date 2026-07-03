from __future__ import annotations

import logging

from app.database.database import Base
from app.database.database import SessionLocal
from app.database.database import engine
from app.models.company import Company


logger = logging.getLogger(__name__)


def seed_database() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        if db.query(Company).count() > 0:
            return

        companies = [
            Company(
                ticker="TCS",
                company_name="Tata Consultancy Services",
                revenue=240000,
                profit=46000,
                eps=145,
                pe_ratio=31,
            ),
            Company(
                ticker="INFY",
                company_name="Infosys",
                revenue=165000,
                profit=27000,
                eps=72,
                pe_ratio=29,
            ),
            Company(
                ticker="RELIANCE",
                company_name="Reliance Industries",
                revenue=920000,
                profit=80000,
                eps=110,
                pe_ratio=25,
            ),
            Company(
                ticker="WIPRO",
                company_name="Wipro",
                revenue=90000,
                profit=11000,
                eps=21,
                pe_ratio=22,
            ),
            Company(
                ticker="HCLTECH",
                company_name="HCL Technologies",
                revenue=105000,
                profit=15000,
                eps=55,
                pe_ratio=24,
            ),
        ]

        db.add_all(companies)
        db.commit()
        logger.info("Database seeded successfully with starter companies.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
