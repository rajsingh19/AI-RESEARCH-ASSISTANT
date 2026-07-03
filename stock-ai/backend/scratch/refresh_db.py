import logging
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_dir))

from app.database.database import Base, engine, SessionLocal
from app.seed import seed_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def refresh_db():
    logger.info("Dropping all existing database tables...")
    Base.metadata.drop_all(bind=engine)
    logger.info("Creating all database tables with expanded schema...")
    Base.metadata.create_all(bind=engine)
    logger.info("Seeding database with starter companies...")
    seed_database()
    logger.info("Database refreshed successfully!")

if __name__ == "__main__":
    refresh_db()
