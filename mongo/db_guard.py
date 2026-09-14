"""
Hard-enforced database isolation.

This pipeline must NEVER connect to the production website database.
Every entry point (scraper, NLP enrichment, dashboard API) goes through
`get_isolated_db()` so the guard can't be accidentally bypassed by
someone hardcoding a db name somewhere else later.
"""

import os
from pymongo import MongoClient
from pymongo.database import Database

ALLOWED_DB_NAME = "astrology_intelligence"
# Real production database name, confirmed via Atlas (list-databases on
# the adhbhutgyaan-cluster / adhbhutgyaan project): "astrokashi".
# adhbhutgyaan_prod is kept as a placeholder alias in case of a future rename.
FORBIDDEN_DB_NAMES = {"astrokashi", "adhbhutgyaan_prod"}


class DatabaseIsolationError(RuntimeError):
    """Raised when any code path attempts to touch a non-isolated database."""


def get_isolated_db(mongo_uri: str | None = None) -> Database:
    """
    Returns a handle to the astrology_intelligence database ONLY.
    Raises DatabaseIsolationError if MONGO_DB_NAME env var (if set) points
    anywhere else, as a second line of defense beyond the hardcoded name.
    """
    uri = mongo_uri or os.environ.get("MONGODB_URI")
    if not uri:
        raise RuntimeError(
            "MONGODB_URI is not set. Set it in your local .env "
            "(see .env.example) before running any pipeline script."
        )

    override = os.environ.get("MONGO_DB_NAME", ALLOWED_DB_NAME)
    if override in FORBIDDEN_DB_NAMES:
        raise DatabaseIsolationError(
            f"Refusing to connect to '{override}' — this pipeline is "
            f"strictly isolated to '{ALLOWED_DB_NAME}' and must never "
            f"touch the production website database."
        )
    if override != ALLOWED_DB_NAME:
        raise DatabaseIsolationError(
            f"MONGO_DB_NAME is set to '{override}', but this pipeline is "
            f"hardcoded to only operate on '{ALLOWED_DB_NAME}'. Unset "
            f"MONGO_DB_NAME or set it to '{ALLOWED_DB_NAME}' explicitly."
        )

    client = MongoClient(uri)
    return client[ALLOWED_DB_NAME]
