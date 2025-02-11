"""
Database configuration and session management.

This module provides database configuration, session management, and transaction handling
with support for nested transactions using savepoints, proper isolation levels,
and deadlock handling.
"""

import time
from contextlib import contextmanager
from enum import Enum
from typing import Generator, Any, Optional, Callable

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.exc import SQLAlchemyError, OperationalError, DBAPIError

from .config import settings

class TransactionIsolationLevel(Enum):
    """Supported transaction isolation levels."""
    READ_UNCOMMITTED = "READ UNCOMMITTED"
    READ_COMMITTED = "READ COMMITTED"
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"

# Default retry settings
MAX_RETRIES = 3
RETRY_DELAY = 0.1  # seconds

# Create MySQL URL
SQLALCHEMY_DATABASE_URL = (
    f"mysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}@"
    f"{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DB}"
)

# Create SQLAlchemy engine with optimized settings
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,  # Enable automatic reconnection
    pool_size=10,  # Set connection pool size
    max_overflow=20,  # Allow up to 20 connections to overflow from the pool
    pool_timeout=30,  # Connection timeout in seconds
    pool_recycle=1800,  # Recycle connections after 30 minutes
    echo=False,  # Set to True for SQL query logging
    isolation_level="REPEATABLE READ"  # Default isolation level
)

# Create SessionLocal class with transaction settings
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False  # Prevent expired object access after commit
)

# Create Base class for declarative models
Base = declarative_base()

# PUBLIC_INTERFACE
@contextmanager
def transaction(
    session: Session,
    isolation_level: Optional[TransactionIsolationLevel] = None,
    retries: int = MAX_RETRIES
) -> Generator[Session, None, None]:
    """
    Context manager for handling database transactions with automatic rollback on error
    and retry mechanism for deadlocks.
    
    Args:
        session (Session): SQLAlchemy session instance
        isolation_level (Optional[TransactionIsolationLevel]): Transaction isolation level
        retries (int): Number of retries for deadlock situations
        
    Yields:
        Session: The active database session
        
    Raises:
        SQLAlchemyError: If any database operation fails after all retries
    """
    attempt = 0
    last_error = None

    while attempt <= retries:
        try:
            if isolation_level:
                session.execute(text(f"SET TRANSACTION ISOLATION LEVEL {isolation_level.value}"))
            
            yield session
            session.commit()
            return
        except (OperationalError, DBAPIError) as e:
            if attempt < retries and "deadlock" in str(e).lower():
                session.rollback()
                attempt += 1
                time.sleep(RETRY_DELAY * attempt)
                last_error = e
                continue
            session.rollback()
            raise
        except SQLAlchemyError as e:
            session.rollback()
            raise
        finally:
            session.expire_all()
    
    if last_error:
        raise last_error

# PUBLIC_INTERFACE
@contextmanager
def nested_transaction(
    session: Session,
    isolation_level: Optional[TransactionIsolationLevel] = None
) -> Generator[Session, None, None]:
    """
    Context manager for handling nested transactions using savepoints with proper
    isolation level support.
    
    Args:
        session (Session): SQLAlchemy session instance
        isolation_level (Optional[TransactionIsolationLevel]): Transaction isolation level
        
    Yields:
        Session: The active database session with savepoint
        
    Raises:
        SQLAlchemyError: If any database operation fails
    """
    if not session.in_transaction():
        with transaction(session, isolation_level=isolation_level):
            with session.begin_nested():
                yield session
    else:
        with session.begin_nested():
            if isolation_level:
                session.execute(text(f"SET TRANSACTION ISOLATION LEVEL {isolation_level.value}"))
            yield session

def get_db() -> Generator[Session, None, None]:
    """
    Get database session with automatic cleanup.
    
    Yields:
        Session: Database session
        
    Note:
        This function should be used as a FastAPI dependency.
        The session is automatically closed after the request is completed.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Track active transactions per session
def track_transaction(func: Callable) -> Callable:
    """
    Decorator to track active transactions per session.
    
    Args:
        func (Callable): Function to wrap
        
    Returns:
        Callable: Wrapped function with transaction tracking
    """
    def wrapper(session: Session, *args, **kwargs):
        if not hasattr(session, '_transaction_count'):
            session._transaction_count = 0
        session._transaction_count += 1
        try:
            return func(session, *args, **kwargs)
        finally:
            session._transaction_count -= 1
    return wrapper

@event.listens_for(Session, 'after_begin')
def receive_after_begin(session: Session, transaction: Any, connection: Any) -> None:
    """
    Event listener that executes after a transaction begins.
    Sets the transaction isolation level to REPEATABLE READ by default if not already set.
    
    Args:
        session (Session): The database session
        transaction (Any): The transaction object
        connection (Any): The database connection
    """
    if not hasattr(session, '_isolation_level_set'):
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        session._isolation_level_set = True

@event.listens_for(Session, 'after_rollback')
def receive_after_rollback(session: Session) -> None:
    """
    Event listener that executes after a transaction rollback.
    Ensures all objects in the session are expired after rollback.
    
    Args:
        session (Session): The database session
    """
    session.expire_all()
