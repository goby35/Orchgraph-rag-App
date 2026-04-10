from __future__ import annotations

from contextlib import contextmanager

from neo4j import GraphDatabase

from pipeline.config import get_logger, settings

logger = get_logger(__name__)


def get_neo4j_driver(
    uri: str | None = None,
    user: str | None = None,
    password: str | None = None,
):
    """Create a Neo4j driver using Aura-aware settings."""
    uri = uri or settings.neo4j_uri
    user = user or settings.neo4j_user
    password = password or settings.neo4j_password

    logger.info("Connecting to Neo4j: %s...", uri[:30])
    logger.info("User: %s", user)
    logger.info("Is Aura: %s", settings.is_aura)

    driver = GraphDatabase.driver(uri, auth=(user, password))

    try:
        driver.verify_connectivity()
        logger.info("Neo4j connection verified OK")
    except Exception as exc:
        logger.error("Neo4j connection FAILED: %s", exc)
        driver.close()
        raise

    return driver


@contextmanager
def get_neo4j_session(database: str | None = None):
    """Provide a verified Neo4j session and close driver automatically."""
    driver = get_neo4j_driver()
    db = database or settings.neo4j_database
    try:
        with driver.session(database=db) as session:
            yield session
    finally:
        driver.close()
