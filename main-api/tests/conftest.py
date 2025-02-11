"""
Pytest configuration and fixtures.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from typing import Generator
from redis import Redis
from contextlib import contextmanager

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.cache import get_redis_client
from app import app

# Test database configuration
TEST_DB_PATH = "test.db"

def get_test_database_url():
    """
    Get test database URL based on DB_TYPE setting.
    For testing, we always use SQLite to avoid external dependencies.
    """
    return f"sqlite:///{TEST_DB_PATH}"

def create_test_engine():
    """
    Create test database engine with appropriate settings for SQLite.
    """
    return create_engine(
        get_test_database_url(),
        connect_args={"check_same_thread": False},  # Required for SQLite
        poolclass=None  # Disable connection pooling for tests
    )

# Create test engine instance
test_engine = create_test_engine()

# Create test SessionLocal
TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine
)


@pytest.fixture(scope="session", autouse=True)
def db_engine():
    """
    Create test database engine and handle database initialization/cleanup.
    This fixture runs automatically for all tests and ensures proper database setup.
    """
    import os
    
    # Remove existing test database if it exists
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    
    # Create all tables
    Base.metadata.create_all(bind=test_engine)
    
    yield test_engine
    
    # Cleanup after all tests
    Base.metadata.drop_all(bind=test_engine)
    
    # Remove test database file
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


@pytest.fixture(scope="function")
def db_session(db_engine) -> Generator:
    """
    Create test database session with proper transaction handling.
    
    This fixture creates an outer transaction that is rolled back after each test,
    ensuring test isolation. It also handles nested transactions properly to avoid
    SQLAlchemy transaction deassociation warnings.
    
    The transaction handling works as follows:
    1. Creates an outer transaction that wraps the entire test
    2. Creates a SAVEPOINT for each nested transaction
    3. Rolls back to the SAVEPOINT when a nested transaction ends
    4. Rolls back the entire outer transaction after the test
    
    This ensures that:
    - Each test runs in isolation
    - Nested transactions don't affect the outer transaction
    - All changes are rolled back after each test
    - No data leaks between tests
    """
    # Connect and begin a transaction
    connection = db_engine.connect()
    transaction = connection.begin()
    
    # Create a session bound to this connection
    session = TestingSessionLocal(bind=connection)
    
    # Begin a nested transaction (using SAVEPOINT)
    nested = connection.begin_nested()
    
    # If the application code calls session.commit, it will only commit up to
    # the SAVEPOINT we created, maintaining the outer transaction
    def end_savepoint(session, transaction):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()
    
    event.listen(session, 'after_transaction_end', end_savepoint)
    
    try:
        yield session
    except Exception as e:
        # Ensure we rollback on any error
        session.rollback()
        raise e
    finally:
        # Remove the listener to prevent memory leaks
        event.remove(session, 'after_transaction_end', end_savepoint)
        # Rollback everything and cleanup
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="function")
def client(db_session) -> Generator:
    """
    Create test client with database session override.
    
    This fixture:
    1. Overrides the database session with our test session
    2. Ensures proper transaction handling during tests
    3. Cleans up after each test
    """
    def override_get_db():
        try:
            yield db_session
        except Exception:
            db_session.rollback()
            raise
        finally:
            # Ensure the session is clean for the next test
            db_session.expire_all()
    
    # Override the database dependency
    app.dependency_overrides[get_db] = override_get_db
    
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        # Clean up dependency overrides
        app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def redis_client() -> Generator:
    """
    Create test Redis client with automatic cleanup.
    """
    # Create Redis client for test database
    client = Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_TEST_DB,
        decode_responses=True
    )
    
    # Clear test database before each test
    client.flushdb()
    
    yield client
    
    # Clear test database after each test
    client.flushdb()
    client.close()


@pytest.fixture(scope="function")
def override_redis_client(redis_client) -> Generator:
    """
    Override Redis client for testing.
    """
    original_get_redis = get_redis_client
    
    @contextmanager
    def mock_get_redis():
        try:
            yield redis_client
        finally:
            pass
    
    # Override the get_redis_client function
    import app.core.cache
    app.core.cache.get_redis_client = mock_get_redis
    
    yield
    
    # Restore original get_redis_client
    app.core.cache.get_redis_client = original_get_redis
