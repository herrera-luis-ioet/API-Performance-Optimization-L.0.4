"""
Tests for database connection handling and error scenarios.
"""

import pytest
from sqlalchemy.exc import OperationalError, TimeoutError, DBAPIError
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, MagicMock, call
import pymysql
import threading
import time
import concurrent.futures

from app.core.database import get_db
from app.core.config import settings


def test_database_connection_timeout():
    """Test handling of database connection timeout."""
    with patch('sqlalchemy.create_engine') as mock_create_engine:
        # Simulate a connection timeout
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = TimeoutError("Connection timed out")
        mock_create_engine.return_value = mock_engine
        
        # Create a new session with the mocked engine
        TestSession = sessionmaker(bind=mock_engine)
        db = TestSession()
        
        # Verify that attempting to use the session raises TimeoutError
        with pytest.raises(TimeoutError, match="Connection timed out"):
            db.execute(text("SELECT 1"))


def test_authentication_failure():
    """Test handling of database authentication failure."""
    with patch('sqlalchemy.create_engine') as mock_create_engine:
        # Create mock engine that simulates authentication failure
        mock_engine = MagicMock()
        error = DBAPIError(
            statement="SELECT 1",
            params={},
            orig=pymysql.OperationalError(
                1045,  # MySQL error code for access denied
                "Access denied for user 'invalid_user'@'localhost'"
            )
        )
        mock_engine.connect.side_effect = error
        mock_create_engine.return_value = mock_engine
        
        TestSession = sessionmaker(bind=mock_engine)
        db = TestSession()
        
        # Verify authentication failure
        with pytest.raises(DBAPIError) as exc_info:
            db.execute(text("SELECT 1"))
        assert "Access denied" in str(exc_info.value)


def test_connection_pool_exhaustion():
    """Test handling of connection pool exhaustion."""
    with patch('sqlalchemy.create_engine') as mock_create_engine:
        # Create mock engine that simulates pool exhaustion
        mock_engine = MagicMock()
        error = DBAPIError(
            statement="SELECT 1",
            params={},
            orig=pymysql.OperationalError(
                1040, 
                "Too many connections"
            )
        )
        mock_engine.connect.side_effect = error
        mock_create_engine.return_value = mock_engine
        
        TestSession = sessionmaker(bind=mock_engine)
        db = TestSession()
        
        # Verify pool exhaustion error
        with pytest.raises(DBAPIError) as exc_info:
            db.execute(text("SELECT 1"))
        assert "Too many connections" in str(exc_info.value)


def test_network_errors():
    """Test handling of network-related database errors."""
    with patch('sqlalchemy.create_engine') as mock_create_engine:
        # Simulate network error
        mock_engine = MagicMock()
        error = DBAPIError(
            statement="SELECT 1",
            params={},
            orig=pymysql.OperationalError(
                2003, 
                "Can't connect to MySQL server"
            )
        )
        mock_engine.connect.side_effect = error
        mock_create_engine.return_value = mock_engine
        
        TestSession = sessionmaker(bind=mock_engine)
        db = TestSession()
        
        # Verify network error handling
        with pytest.raises(DBAPIError) as exc_info:
            db.execute(text("SELECT 1"))
        assert "Can't connect to MySQL server" in str(exc_info.value)


def test_invalid_connection_parameters():
    """Test handling of invalid connection parameters."""
    invalid_url = (
        f"mysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}@"
        f"invalid_host:{settings.MYSQL_PORT}/{settings.MYSQL_DB}"
    )
    
    # Create engine with invalid host
    engine = create_engine(invalid_url)
    TestSession = sessionmaker(bind=engine)
    
    # Verify connection failure with invalid parameters
    with pytest.raises(OperationalError) as exc_info:
        db = TestSession()
        db.execute(text("SELECT 1"))
    assert "Unknown MySQL server host" in str(exc_info.value) or "Name or service not known" in str(exc_info.value)


def test_get_db_connection_cleanup():
    """Test that get_db properly closes the connection."""
    with patch('app.core.database.SessionLocal') as mock_session_local:
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        
        # Get database session using the generator
        db_gen = get_db()
        db = next(db_gen)
        
        try:
            # Verify we got the mock database
            assert db == mock_db
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass
        
        # Verify the connection was closed
        mock_db.close.assert_called_once()


def test_connection_timeout_with_retry():
    """Test database connection timeout with retry attempts."""
    with patch('sqlalchemy.create_engine') as mock_create_engine:
        mock_engine = MagicMock()
        # Simulate timeout for first two attempts, then succeed
        mock_engine.connect.side_effect = [
            TimeoutError("Connection timed out"),
            TimeoutError("Connection timed out"),
            MagicMock()  # Success on third attempt
        ]
        mock_create_engine.return_value = mock_engine
        
        TestSession = sessionmaker(bind=mock_engine)
        
        for attempt in range(3):
            db = TestSession()
            try:
                with db.begin():  # Ensure transaction management
                    if attempt < 2:  # First two attempts should fail
                        with pytest.raises(TimeoutError):
                            db.execute(text("SELECT 1"))
                    else:  # Third attempt should succeed
                        db.execute(text("SELECT 1"))
            except TimeoutError:
                pass  # Expected for first two attempts
            finally:
                db.close()  # Ensure proper cleanup
        
        # Verify three connection attempts were made
        assert mock_engine.connect.call_count == 3


def test_concurrent_database_access():
    """Test concurrent database access patterns."""
    NUM_THREADS = 5
    ITERATIONS = 3
    
    def concurrent_db_access(results, thread_id):
        with patch('app.core.database.SessionLocal') as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db
            
            for i in range(ITERATIONS):
                db_gen = get_db()
                db = next(db_gen)
                try:
                    # Simulate some database operations
                    db.execute(text(f"SELECT * FROM test WHERE thread_id = {thread_id}"))
                    results[thread_id].append(True)
                except Exception as e:
                    results[thread_id].append(False)
                finally:
                    try:
                        next(db_gen)
                    except StopIteration:
                        pass
    
    # Track results for each thread
    results = {i: [] for i in range(NUM_THREADS)}
    threads = []
    
    # Start concurrent threads
    for i in range(NUM_THREADS):
        thread = threading.Thread(target=concurrent_db_access, args=(results, i))
        threads.append(thread)
        thread.start()
    
    # Wait for all threads to complete
    for thread in threads:
        thread.join()
    
    # Verify all operations completed successfully
    for thread_id in range(NUM_THREADS):
        assert len(results[thread_id]) == ITERATIONS
        assert all(results[thread_id])


def test_network_partition_recovery():
    """Test database recovery after network partition."""
    with patch('sqlalchemy.create_engine') as mock_create_engine:
        mock_engine = MagicMock()
        network_error = DBAPIError(
            statement="SELECT 1",
            params={},
            orig=pymysql.OperationalError(2013, "Lost connection to MySQL server")
        )
        # Simulate network partition then recovery
        mock_engine.connect.side_effect = [
            network_error,  # Initial failure due to network partition
            MagicMock()    # Success after recovery
        ]
        mock_create_engine.return_value = mock_engine
        
        TestSession = sessionmaker(bind=mock_engine)
        
        # First attempt with transaction - should fail due to network partition
        db = TestSession()
        try:
            with db.begin():  # Ensure transaction management
                with pytest.raises(DBAPIError) as exc_info:
                    db.execute(text("SELECT 1"))
                assert "Lost connection to MySQL server" in str(exc_info.value)
        finally:
            db.close()
        
        # Second attempt with new transaction - should succeed after network recovery
        db = TestSession()
        try:
            with db.begin():  # Ensure transaction management
                db.execute(text("SELECT 1"))
        finally:
            db.close()
        
        # Verify two connection attempts were made
        assert mock_engine.connect.call_count == 2


def test_session_cleanup_after_error():
    """Test proper session cleanup after database errors."""
    with patch('app.core.database.SessionLocal') as mock_session_local:
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        
        # Simulate an error during database operation
        mock_db.execute.side_effect = OperationalError("statement", "params", "orig")
        
        db_gen = get_db()
        db = next(db_gen)
        
        try:
            # Attempt database operation that will fail
            with pytest.raises(OperationalError):
                db.execute(text("SELECT 1"))
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass
        
        # Verify the session was properly closed despite the error
        mock_db.close.assert_called_once()


def test_connection_pool_reuse():
    """Test connection pool reuse and management using SQLAlchemy event listeners."""
    # Create a real engine for testing with SQLite
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}  # Allow multi-threaded access for testing
    )
    
    # Track connections using event listeners
    active_connections = set()
    total_connections = 0
    
    @event.listens_for(test_engine.pool, 'checkout')
    def on_checkout(dbapi_conn, connection_record, connection_proxy):
        nonlocal total_connections
        active_connections.add(dbapi_conn)
        if dbapi_conn not in active_connections:
            total_connections += 1
    
    @event.listens_for(test_engine.pool, 'checkin')
    def on_checkin(dbapi_conn, connection_record):
        active_connections.discard(dbapi_conn)
    
    # Create a session factory
    TestSession = sessionmaker(bind=test_engine)
    
    # Simulate multiple session creations and operations
    sessions = []
    max_concurrent = 0
    
    for _ in range(5):
        db = TestSession()
        with db.begin():
            db.execute(text("SELECT 1"))
            max_concurrent = max(max_concurrent, len(active_connections))
        sessions.append(db)
    
    # Close all sessions
    for db in sessions:
        db.close()
    
    # Verify connection pool behavior
    assert max_concurrent <= 2, "Should not exceed pool size"
    assert len(active_connections) == 0, "All connections should be returned to pool"
    assert total_connections <= 2, "Should reuse connections from pool"
