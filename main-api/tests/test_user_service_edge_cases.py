"""
Additional test cases for user service module focusing on edge cases and error scenarios.
"""

import pytest
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError
from redis import RedisError, ConnectionError

from app.services.user import (
    create_user, get_user, get_user_by_email, get_users,
    update_user, delete_user, USER_KEY, USER_EMAIL_KEY,
    USERS_LIST_KEY, USER_CACHE_EXPIRE, USERS_LIST_CACHE_EXPIRE
)
from app.schemas.user import UserCreate, UserUpdate
from app.models.user import User

# Test data
TEST_USER_DATA = {
    "email": "test@example.com",
    "username": "testuser",
    "password": "testpass123",
    "full_name": "Test User",
    "is_active": True,
    "is_superuser": False
}

@pytest.fixture
def mock_db():
    """Mock database session with context manager support."""
    db = Mock(spec=Session)
    db.__enter__ = Mock(return_value=db)
    db.__exit__ = Mock(return_value=None)
    return db

@pytest.fixture
def mock_user():
    """Mock User instance."""
    user = Mock(spec=User)
    user.id = 1
    user.email = TEST_USER_DATA["email"]
    user.username = TEST_USER_DATA["username"]
    user.full_name = TEST_USER_DATA["full_name"]
    user.is_active = TEST_USER_DATA["is_active"]
    user.is_superuser = TEST_USER_DATA["is_superuser"]
    user.created_at = "2024-02-19T12:00:00"
    user.updated_at = "2024-02-19T12:00:00"
    user._cache_version = "1.1"
    return user

@pytest.mark.asyncio
async def test_create_user_invalid_data(mock_db):
    """Test user creation with invalid data."""
    with pytest.raises(ValueError) as exc_info:
        # This will raise a validation error before even reaching the database
        UserCreate(
            email="not_an_email",  # Invalid email format
            username="",  # Empty username
            password="short",  # Too short password
            full_name="Test User",
            is_active=True,
            is_superuser=False
        )
    
    assert "not a valid email" in str(exc_info.value).lower()

@pytest.mark.asyncio
async def test_update_user_concurrent_modification(mock_db, mock_user):
    """Test user update with concurrent modifications."""
    user_id = 1
    update_data = UserUpdate(email="new@example.com")
    mock_user.email = "old@example.com"

    with patch("app.services.user.get_user") as mock_get_user, \
         patch("app.services.user.transaction_context") as mock_transaction:
        
        mock_get_user.return_value = mock_user
        mock_transaction.side_effect = OperationalError(
            None, None, "Row was updated or deleted by another transaction"
        )

        with pytest.raises(OperationalError) as exc_info:
            update_user(mock_db, user_id, update_data)

        assert "Row was updated or deleted by another transaction" in str(exc_info.value)

@pytest.mark.asyncio
async def test_delete_user_with_cache_failure(mock_db, mock_user):
    """Test user deletion with cache failures."""
    user_id = 1
    mock_user.email = TEST_USER_DATA["email"]

    with patch("app.services.user.get_user") as mock_get_user, \
         patch("app.services.user.cache_delete") as mock_cache_delete:
        
        mock_get_user.return_value = mock_user
        mock_cache_delete.side_effect = RedisError("Cache connection failed")

        result = delete_user(mock_db, user_id)

        assert result is True  # Operation should succeed despite cache failures
        mock_db.delete.assert_called_once_with(mock_user)
        mock_db.commit.assert_called_once()

@pytest.mark.asyncio
async def test_user_retrieval_database_error(mock_db):
    """Test user retrieval with database errors."""
    user_id = 1

    with patch("app.services.user.cache_get") as mock_cache_get:
        mock_cache_get.return_value = None
        mock_db.query.side_effect = OperationalError(
            None, None, "Database connection lost"
        )

        with pytest.raises(OperationalError):
            get_user(mock_db, user_id)

@pytest.mark.asyncio
async def test_pagination_edge_cases(mock_db, mock_user):
    """Test pagination edge cases in get_users."""
    # Test with negative skip
    with pytest.raises(ValueError) as exc_info:
        get_users(mock_db, skip=-1, limit=10)
    assert "skip must be non-negative" in str(exc_info.value)

    # Test with zero limit
    with pytest.raises(ValueError) as exc_info:
        get_users(mock_db, skip=0, limit=0)
    assert "limit must be positive" in str(exc_info.value)

    # Test with very large limit
    mock_db.query.return_value.offset.return_value.limit.return_value.all.return_value = [mock_user] * 1000
    with patch("app.services.user.cache_get") as mock_cache_get, \
         patch("app.services.user.cache_set") as mock_cache_set:
        
        mock_cache_get.return_value = None
        mock_cache_set.return_value = True
        
        users = get_users(mock_db, skip=0, limit=1000)
        assert len(users) == 1000

@pytest.mark.asyncio
async def test_transaction_retry_deadlock(mock_db, mock_user):
    """Test transaction retry mechanism during deadlock."""
    user_id = 1
    update_data = UserUpdate(email="new@example.com")
    mock_user.email = "old@example.com"

    with patch("app.services.user.get_user") as mock_get_user, \
         patch("app.services.user.transaction_context") as mock_transaction:
        
        mock_get_user.return_value = mock_user
        # Simulate deadlock on first two attempts, success on third
        mock_db.commit.side_effect = [
            OperationalError(None, None, "Deadlock found"),
            OperationalError(None, None, "Deadlock found"),
            None
        ]

        result = update_user(mock_db, user_id, update_data)
        assert result == mock_user
        assert mock_db.commit.call_count == 3
        assert mock_db.rollback.call_count == 2

@pytest.mark.asyncio
async def test_transaction_retry_max_retries_exceeded(mock_db, mock_user):
    """Test transaction retry mechanism when max retries are exceeded."""
    user_id = 1
    update_data = UserUpdate(email="new@example.com")
    mock_user.email = "old@example.com"

    with patch("app.services.user.get_user") as mock_get_user:
        mock_get_user.return_value = mock_user
        # Simulate persistent deadlock
        mock_db.commit.side_effect = OperationalError(None, None, "Deadlock found")

        with pytest.raises(OperationalError) as exc_info:
            update_user(mock_db, user_id, update_data)
        
        assert "Deadlock found" in str(exc_info.value)
        assert mock_db.commit.call_count >= 3  # MAX_RETRIES
        assert mock_db.rollback.call_count >= 3

@pytest.mark.asyncio
async def test_cache_version_validation_unsupported(mock_db, mock_user):
    """Test handling of unsupported cache version."""
    user_id = 1
    unsupported_version_data = {
        "id": mock_user.id,
        "email": mock_user.email,
        "username": mock_user.username,
        "full_name": mock_user.full_name,
        "is_active": mock_user.is_active,
        "is_superuser": mock_user.is_superuser,
        "created_at": str(mock_user.created_at),
        "updated_at": str(mock_user.updated_at),
        "_cache_version": "0.8"  # Unsupported version
    }

    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    with patch("app.services.user.cache_get") as mock_cache_get, \
         patch("app.services.user.cache_delete") as mock_cache_delete, \
         patch("app.services.user.cache_set") as mock_cache_set:
        
        mock_cache_get.return_value = unsupported_version_data
        mock_cache_delete.return_value = True
        mock_cache_set.return_value = True

        result = get_user(mock_db, user_id)

        assert result == mock_user
        mock_cache_get.assert_called_once()
        mock_cache_delete.assert_called_once()  # Should delete invalid cache
        mock_cache_set.assert_called_once()  # Should set new cache with current version

@pytest.mark.asyncio
async def test_nested_transaction_error_handling(mock_db, mock_user):
    """Test error handling in nested transactions during user update."""
    user_id = 1
    update_data = UserUpdate(email="new@example.com")
    mock_user.email = "old@example.com"

    with patch("app.services.user.get_user") as mock_get_user:
        mock_get_user.return_value = mock_user
        
        # Simulate error in nested transaction
        mock_nested = Mock()
        mock_nested.__enter__ = Mock(side_effect=OperationalError(None, None, "Nested transaction error"))
        mock_nested.__exit__ = Mock(return_value=None)
        mock_db.begin_nested.return_value = mock_nested

        with pytest.raises(RuntimeError) as exc_info:
            update_user(mock_db, user_id, update_data)

        assert "Failed to update user" in str(exc_info.value)
        mock_db.rollback.assert_called_once()

@pytest.mark.asyncio
async def test_cache_data_corruption_missing_fields(mock_db, mock_user):
    """Test handling of corrupted cache data with missing required fields."""
    user_id = 1
    corrupted_data = {
        "id": mock_user.id,
        "email": mock_user.email,
        # Missing other required fields
        "_cache_version": "1.1"
    }

    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    with patch("app.services.user.cache_get") as mock_cache_get, \
         patch("app.services.user.cache_delete") as mock_cache_delete, \
         patch("app.services.user.cache_set") as mock_cache_set:
        
        mock_cache_get.return_value = corrupted_data
        mock_cache_delete.return_value = True
        mock_cache_set.return_value = True

        result = get_user(mock_db, user_id)

        assert result == mock_user
        mock_cache_get.assert_called_once()
        mock_cache_delete.assert_called_once()  # Should delete corrupted cache
        mock_cache_set.assert_called_once()  # Should set new cache with all fields

@pytest.mark.asyncio
async def test_redis_connection_pool_exhaustion(mock_db, mock_user):
    """Test handling of Redis connection pool exhaustion."""
    user_id = 1
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    with patch("app.services.user.cache_get") as mock_cache_get, \
         patch("app.services.user.cache_set") as mock_cache_set:
        
        # Simulate Redis connection pool exhaustion
        mock_cache_get.side_effect = RedisError("Connection pool exhausted")
        mock_cache_set.side_effect = RedisError("Connection pool exhausted")

        result = get_user(mock_db, user_id)

        assert result == mock_user  # Should still return data from DB
        mock_cache_get.assert_called_once()
        mock_cache_set.assert_not_called()  # Should not try to set cache after connection error

@pytest.mark.asyncio
async def test_cache_data_type_validation(mock_db, mock_user):
    """Test validation of cache data types."""
    user_id = 1
    invalid_types_data = {
        "id": "not_an_integer",  # Wrong type
        "email": 12345,  # Wrong type
        "username": ["invalid"],  # Wrong type
        "full_name": mock_user.full_name,
        "is_active": "not_a_boolean",  # Wrong type
        "is_superuser": mock_user.is_superuser,
        "created_at": str(mock_user.created_at),
        "updated_at": str(mock_user.updated_at),
        "_cache_version": "1.1"
    }

    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    with patch("app.services.user.cache_get") as mock_cache_get, \
         patch("app.services.user.cache_delete") as mock_cache_delete, \
         patch("app.services.user.cache_set") as mock_cache_set:
        
        mock_cache_get.return_value = invalid_types_data
        mock_cache_delete.return_value = True
        mock_cache_set.return_value = True

        result = get_user(mock_db, user_id)

        assert result == mock_user
        mock_cache_get.assert_called_once()
        mock_cache_delete.assert_called_once()  # Should delete invalid cache
        mock_cache_set.assert_called_once()  # Should set new cache with correct types

@pytest.mark.asyncio
async def test_email_uniqueness_validation(mock_db, mock_user):
    """Test email uniqueness validation during user operations."""
    # Test create user with existing email
    user_data = UserCreate(**TEST_USER_DATA)

    with patch("app.services.user.transaction_context") as mock_transaction:
        mock_db.add.side_effect = IntegrityError(
            None, None, "Duplicate entry 'test@example.com' for key 'users.email'"
        )
        mock_db.rollback.return_value = None

        with pytest.raises(ValueError) as exc_info:
            create_user(mock_db, user_data)
        assert "already exists" in str(exc_info.value)

    # Test update user with existing email
    user_id = 2  # Different from mock_user.id
    update_data = UserUpdate(email=TEST_USER_DATA["email"])
    
    with patch("app.services.user.get_user") as mock_get_user, \
         patch("app.services.user.transaction_context") as mock_transaction:
        
        mock_get_user.return_value = mock_user
        mock_db.in_transaction.return_value = True
        mock_nested = Mock()
        mock_nested.__enter__ = Mock(return_value=mock_nested)
        mock_nested.__exit__ = Mock(return_value=None)
        mock_db.begin_nested.return_value = mock_nested
        mock_db.commit.side_effect = IntegrityError(
            None, None, "Duplicate entry 'test@example.com' for key 'users.email'"
        )
        mock_db.rollback.return_value = None

        with pytest.raises(ValueError) as exc_info:
            update_user(mock_db, user_id, update_data)
        assert "already in use" in str(exc_info.value)
