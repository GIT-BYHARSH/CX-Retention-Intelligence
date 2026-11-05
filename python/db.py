"""Shared database connection for all analysis scripts and notebooks.

Two ways to connect:
  1. Local (default): DB_USER / DB_PASSWORD / DB_HOST / DB_PORT / DB_NAME from the private .env file.
  2. Cloud (the deployed demo): one DATABASE_URL setting, for example a Neon read-only connection string.
     If DATABASE_URL is set it wins, so the same code runs on a laptop and in the cloud.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

# Read the secrets from the .env file in the project root (absent in the cloud, which is fine)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _sqlalchemy_url(raw):
    """Accept postgres:// or postgresql:// URLs and make them work with the psycopg2 driver."""
    for prefix in ("postgres://", "postgresql://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg2://" + raw[len(prefix):]
    return raw


def get_engine():
    """Return a SQLAlchemy engine connected to the mediops database."""
    cloud_url = os.environ.get("DATABASE_URL", "").strip()
    if cloud_url:
        # pool_pre_ping: free cloud databases go to sleep; this reconnects instead of failing
        return create_engine(_sqlalchemy_url(cloud_url), pool_pre_ping=True)
    url = URL.create(
        drivername="postgresql+psycopg2",
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        database=os.environ["DB_NAME"],
    )
    return create_engine(url)
