"""
Unit tests for User service with Redis cache integration.
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
    # Add context manager support
    db.__enter__ = Mock(return_value=db)
    db.__exit__ = Mock(return_value=None)
    return db

@pytest.fixture
def mock_db_with_unique_email():
    """Mock database session with unique email check and context manager support."""
    db = Mock(spec=Session)
    db.query.return_value.filter.return_value.first.return_value = None
    # Add context manager support
    db.__enter__ = Mock(return_value=db)
    db.__exit__ = Mock(return_value=None)
    return db

@pytest.fixture
def mock_user():
    """Mock User instance with context manager support."""
    user = Mock(spec=User)
    user.id = 1
    user.email = TEST_USER_DATA["email"]
    user.username = TEST_USER_DATA["username"]
    user.full_name = TEST_USER_DATA["full_name"]
    user.is_active = TEST_USER_DATA["is_active"]
    user.is_superuser = TEST_USER_DATA["is_superuser"]
    user.created_at = "2024-02-19T12:00:00"
    user.updated_at = "2024-02-19T12:00:00"
    # Add cache version to mock user for version validation
    user._cache_version = "1.1"
    # Add context manager support
    user.__enter__ = Mock(return_value=user)
    user.__exit__ = Mock(return_value=None)
    return user

@pytest.fixture
def mock_user_old_version():
    """Mock User instance with old cache version and context manager support."""
    user = Mock(spec=User)
    user.id = 1
    user.email = TEST_USER_DATA["email"]
    user.username = TEST_USER_DATA["username"]
    user.full_name = TEST_USER_DATA["full_name"]
    user.is_active = TEST_USER_DATA["is_active"]
    user.is_superuser = TEST_USER_DATA["is_superuser"]
    user.created_at = "2024-02-19T12:00:00"
    user.updated_at = "2024-02-19T12:00:00"
    # Add old cache version for compatibility testing
    user._cache_version = "1.0"
    # Add context manager support
    user.__enter__ = Mock(return_value=user)
    user.__exit__ = Mock(return_value=None)
    return user

@pytest.mark.asyncio
async def test_create_user_success(mock_db, mock_user):
    """Test successful user creation with cache."""
    user_data = UserCreate(**TEST_USER_DATA)
    mock_db.add.return_value = None
    mock_db.commit.return_value = None
    mock_db.refresh.return_value = None
    mock_user.id = 1

    with patch("app.services.user.get_password_hash") as mock_hash, \
         patch("app.services.user.User") as mock_user_class, \
         patch("app.services.user.cache_set") as mock_cache_set, \
         patch("app.services.user.cache_clear_pattern") as mock_cache_clear:
        
        mock_hash.return_value = "hashed_password"
        mock_user_class.return_value = mock_user
        mock_cache_set.return_value = True
        mock_cache_clear.return_value = True

        result = create_user(mock_db, user_data)

        assert result == mock_user
        expected_cache_data = {
            "id": mock_user.id,
            "email": mock_user.email,
            "username": mock_user.username,
            "full_name": mock_user.full_name,
            "is_active": mock_user.is_active,
            "is_superuser": mock_user.is_superuser,
            "created_at": str(mock_user.created_at),
            "updated_at": str(mock_user.updated_at),
            "_cache_version": "1.1"
        }
        mock_cache_set.assert_any_call(
            USER_KEY.format(mock_user.id),
            expected_cache_data,
            USER_CACHE_EXPIRE
        )
        mock_cache_set.assert_any_call(
            USER_EMAIL_KEY.format(mock_user.email),
            expected_cache_data,
            USER_CACHE_EXPIRE
        )
        mock_cache_clear.assert_called_once_with(USERS_LIST_KEY.format("*", "*"))

@pytest.mark.asyncio
async def test_create_user_duplicate_error(mock_db):
    """Test user creation with duplicate email/username."""
    user_data = UserCreate(**TEST_USER_DATA)
    mock_db.add.side_effect = IntegrityError(None, None, None)

    with pytest.raises(ValueError) as exc_info:
        create_user(mock_db, user_data)
    
    assert str(exc_info.value) == "User with this email or username already exists"
    mock_db.rollback.assert_called_once()

@pytest.mark.asyncio
async def test_get_user_cache_hit(mock_db, mock_user):
    """Test get_user with cache hit."""
    user_id = 1
    cached_user_data = {
        "id": user_id,
        "email": TEST_USER_DATA["email"],
        "username": TEST_USER_DATA["username"],
        "full_name": TEST_USER_DATA["full_name"],
        "is_active": TEST_USER_DATA["is_active"],
        "is_superuser": TEST_USER_DATA["is_superuser"],
        "created_at": "2024-02-19T12:00:00",
        "updated_at": "2024-02-19T12:00:00",
        "_cache_version": "1.1"
    }

    with patch("app.services.user.cache_get") as mock_cache_get, \
         patch("app.services.user.User") as mock_user_class:
        
        mock_cache_get.return_value = cached_user_data
        mock_user_class.return_value = mock_user

        result = get_user(mock_db, user_id)

        assert result == mock_user
        mock_cache_get.assert_called_once_with(USER_KEY.format(user_id))
        mock_db.query.assert_not_called()

@pytest.mark.asyncio
async def test_get_user_cache_miss(mock_db, mock_user):
    """Test get_user with cache miss."""
    user_id = 1
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    with patch("app.services.user.cache_get") as mock_cache_get, \
         patch("app.services.user.cache_set") as mock_cache_set:
        
        mock_cache_get.return_value = None
        mock_cache_set.return_value = True

        result = get_user(mock_db, user_id)

        assert result == mock_user
        mock_cache_get.assert_called_once_with(USER_KEY.format(user_id))
        mock_cache_set.assert_called_once()
        mock_db.query.assert_called_once()

@pytest.mark.asyncio
async def test_get_user_by_email_cache_hit(mock_db, mock_user):
    """Test get_user_by_email with cache hit."""
    email = TEST_USER_DATA["email"]
    cached_user_data = {
        "id": 1,
        "email": email,
        "username": TEST_USER_DATA["username"],
        "full_name": TEST_USER_DATA["full_name"],
        "is_active": TEST_USER_DATA["is_active"],
        "is_superuser": TEST_USER_DATA["is_superuser"],
        "created_at": "2024-02-19T12:00:00",
        "updated_at": "2024-02-19T12:00:00",
        "_cache_version": "1.1"
    }

    with patch("app.services.user.cache_get") as mock_cache_get, \
         patch("app.services.user.User") as mock_user_class:
        
        mock_cache_get.return_value = cached_user_data
        mock_user_class.return_value = mock_user

        result = get_user_by_email(mock_db, email)

        assert result == mock_user
        mock_cache_get.assert_called_once_with(USER_EMAIL_KEY.format(email))
        mock_db.query.assert_not_called()

@pytest.mark.asyncio
async def test_get_users_cache_hit(mock_db, mock_user):
    """Test get_users with cache hit."""
    skip = 0
    limit = 10
    cached_users_data = [{
        "id": 1,
        "email": TEST_USER_DATA["email"],
        "username": TEST_USER_DATA["username"],
        "full_name": TEST_USER_DATA["full_name"],
        "is_active": TEST_USER_DATA["is_active"],
        "is_superuser": TEST_USER_DATA["is_superuser"],
        "created_at": "2024-02-19T12:00:00",
        "updated_at": "2024-02-19T12:00:00",
        "_cache_version": "1.1"
    }]

    with patch("app.services.user.cache_get") as mock_cache_get, \
         patch("app.services.user.User") as mock_user_class:
        
        mock_cache_get.return_value = cached_users_data
        mock_user_class.return_value = mock_user

        result = get_users(mock_db, skip, limit)

        assert len(result) == 1
        assert result[0] == mock_user
        mock_cache_get.assert_called_once_with(USERS_LIST_KEY.format(skip, limit))
        mock_db.query.assert_not_called()

@pytest.mark.asyncio
async def test_update_user_success(mock_db_with_unique_email, mock_user):
    """Test successful user update with cache invalidation."""
    user_id = 1
    update_data = UserUpdate(email="new@example.com")
    mock_user.email = "old@example.com"

    with patch("app.services.user.get_user") as mock_get_user, \
         patch("app.services.user.cache_delete") as mock_cache_delete, \
         patch("app.services.user.cache_set") as mock_cache_set, \
         patch("app.services.user.cache_clear_pattern") as mock_cache_clear:
        
        mock_get_user.return_value = mock_user
        mock_cache_delete.return_value = True
        mock_cache_set.return_value = True
        mock_cache_clear.return_value = True

        result = update_user(mock_db_with_unique_email, user_id, update_data)

        assert result == mock_user
        mock_cache_delete.assert_any_call(USER_KEY.format(user_id))
        mock_cache_delete.assert_any_call(USER_EMAIL_KEY.format("old@example.com"))
        mock_cache_set.assert_called()
        mock_cache_clear.assert_called_once_with(USERS_LIST_KEY.format("*", "*"))

@pytest.mark.asyncio
async def test_delete_user_success(mock_db, mock_user):
    """Test successful user deletion with cache invalidation."""
    user_id = 1
    mock_user.email = TEST_USER_DATA["email"]

    with patch("app.services.user.get_user") as mock_get_user, \
         patch("app.services.user.cache_delete") as mock_cache_delete, \
         patch("app.services.user.cache_clear_pattern") as mock_cache_clear:
        
        mock_get_user.return_value = mock_user
        mock_cache_delete.return_value = True
        mock_cache_clear.return_value = True

        result = delete_user(mock_db, user_id)

        assert result is True
        mock_db.delete.assert_called_once_with(mock_user)
        mock_db.commit.assert_called_once()
        mock_cache_delete.assert_any_call(USER_KEY.format(user_id))
        mock_cache_delete.assert_any_call(USER_EMAIL_KEY.format(mock_user.email))
        mock_cache_clear.assert_called_once_with(USERS_LIST_KEY.format("*", "*"))

@pytest.mark.asyncio
async def test_delete_user_not_found(mock_db):
    """Test user deletion when user not found."""
    user_id = 999

    with patch("app.services.user.get_user") as mock_get_user:
        mock_get_user.return_value = None

        result = delete_user(mock_db, user_id)

        assert result is False
        mock_db.delete.assert_not_called()
        mock_db.commit.assert_not_called()

@pytest.mark.asyncio
async def test_database_connection_failure(mock_db):
    """Test handling of database connection failure."""
    user_id = 1
    mock_db.query.side_effect = OperationalError(None, None, None)

    with patch("app.services.user.cache_get") as mock_cache_get:
        mock_cache_get.return_value = None

        with pytest.raises(OperationalError):
            get_user(mock_db, user_id)

        mock_cache_get.assert_called_once()
        mock_db.query.assert_called_once()

@pytest.mark.asyncio
async def test_corrupted_cache_data(mock_db, mock_user):
    """Test handling of corrupted cache data."""
    user_id = 1
    corrupted_data = {
        "id": 1,
        "email": "test@example.com",
        "_cache_version": "1.1"
    }  # Missing required fields but has version
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
        mock_cache_set.assert_called_once()  # Should set new cache
        mock_db.query.assert_called_once()

@pytest.mark.asyncio
async def test_cache_multi_set_failure(mock_db, mock_user):
    """Test handling of cache multi-set operation failure."""
    skip = 0
    limit = 10
    mock_db.query.return_value.offset.return_value.limit.return_value.all.return_value = [mock_user]

    with patch("app.services.user.cache_get") as mock_cache_get, \
         patch("app.services.user.cache_set") as mock_cache_set, \
         patch("app.services.user.cache_multi_set") as mock_cache_multi_set:
        
        mock_cache_get.return_value = None
        mock_cache_set.return_value = True
        mock_cache_multi_set.return_value = False  # Multi-set operation fails

        result = get_users(mock_db, skip, limit)

        assert len(result) == 1
        assert result[0] == mock_user
        mock_cache_get.assert_called_once()
        mock_cache_set.assert_called_once()
        mock_cache_multi_set.assert_called_once()

@pytest.mark.asyncio
async def test_cache_clear_pattern_failure(mock_db_with_unique_email, mock_user):
    """Test handling of cache pattern clearing failure."""
    user_id = 1
    update_data = UserUpdate(email="new@example.com")
    mock_user.email = "old@example.com"

    with patch("app.services.user.get_user") as mock_get_user, \
         patch("app.services.user.cache_delete") as mock_cache_delete, \
         patch("app.services.user.cache_set") as mock_cache_set, \
         patch("app.services.user.cache_clear_pattern") as mock_cache_clear:
        
        mock_get_user.return_value = mock_user
        mock_cache_delete.return_value = True
        mock_cache_set.return_value = True
        mock_cache_clear.return_value = False  # Pattern clearing fails

        result = update_user(mock_db_with_unique_email, user_id, update_data)

        assert result == mock_user
        mock_cache_delete.assert_any_call(USER_KEY.format(user_id))
        mock_cache_delete.assert_any_call(USER_EMAIL_KEY.format("old@example.com"))
        mock_cache_set.assert_called()
        mock_cache_clear.assert_called_once_with(USERS_LIST_KEY.format("*", "*"))

@pytest.mark.asyncio
async def test_transaction_rollback_on_error(mock_db_with_unique_email, mock_user):
    """Test transaction rollback on database error during update."""
    user_id = 1
    update_data = UserUpdate(email="new@example.com")
    mock_db_with_unique_email.commit.side_effect = OperationalError(None, None, None)

    with patch("app.services.user.get_user") as mock_get_user, \
         patch("app.services.user.cache_delete") as mock_cache_delete, \
         patch("app.services.user.cache_set") as mock_cache_set, \
         patch("app.services.user.cache_clear_pattern") as mock_cache_clear:
        
        mock_get_user.return_value = mock_user
        mock_cache_delete.return_value = True
        mock_cache_set.return_value = True
        mock_cache_clear.return_value = True

        with pytest.raises(RuntimeError) as exc_info:
            update_user(mock_db_with_unique_email, user_id, update_data)

        assert "Failed to update user" in str(exc_info.value)
        mock_db_with_unique_email.rollback.assert_called_once()

@pytest.mark.asyncio
async def test_cache_operations_during_delete(mock_db, mock_user):
    """Test cache operations during user deletion with partial failures."""
    user_id = 1
    mock_user.email = TEST_USER_DATA["email"]

    with patch("app.services.user.get_user") as mock_get_user, \
         patch("app.services.user.cache_delete") as mock_cache_delete, \
         patch("app.services.user.cache_clear_pattern") as mock_cache_clear:
        
        mock_get_user.return_value = mock_user
        # Simulate partial cache operation failures
        mock_cache_delete.side_effect = [True, False]  # First succeeds, second fails
        mock_cache_clear.return_value = False

        result = delete_user(mock_db, user_id)

        assert result is True  # Operation should succeed despite cache failures
        mock_db.delete.assert_called_once_with(mock_user)
        mock_db.commit.assert_called_once()
        assert mock_cache_delete.call_count == 2
        mock_cache_clear.assert_called_once()

@pytest.mark.asyncio
async def test_cache_version_compatibility(mock_db, mock_user_old_version):
    """Test compatibility with old cache version."""
    user_id = 1
    old_version_data = {
        "id": mock_user_old_version.id,
        "email": mock_user_old_version.email,
        "username": mock_user_old_version.username,
        "full_name": mock_user_old_version.full_name,
        "is_active": mock_user_old_version.is_active,
        "is_superuser": mock_user_old_version.is_superuser,
        "created_at": str(mock_user_old_version.created_at),
        "updated_at": str(mock_user_old_version.updated_at),
        "_cache_version": "1.0"  # Old version
    }

    with patch("app.services.user.cache_get") as mock_cache_get, \
         patch("app.services.user.cache_set") as mock_cache_set, \
         patch("app.services.user.User") as mock_user_class:
        
        mock_cache_get.return_value = old_version_data
        mock_cache_set.return_value = True
        mock_user_class.return_value = mock_user_old_version

        result = get_user(mock_db, user_id)

        assert result == mock_user_old_version
        mock_cache_get.assert_called_once()
        # Should not trigger cache update since version 1.0 is still supported
        mock_cache_set.assert_not_called()

@pytest.mark.asyncio
async def test_invalid_cache_version(mock_db, mock_user):
    """Test handling of invalid cache version."""
    user_id = 1
    invalid_version_data = {
        "id": mock_user.id,
        "email": mock_user.email,
        "username": mock_user.username,
        "full_name": mock_user.full_name,
        "is_active": mock_user.is_active,
        "is_superuser": mock_user.is_superuser,
        "created_at": str(mock_user.created_at),
        "updated_at": str(mock_user.updated_at),
        "_cache_version": "0.9"  # Unsupported version
    }

    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    with patch("app.services.user.cache_get") as mock_cache_get, \
         patch("app.services.user.cache_delete") as mock_cache_delete, \
         patch("app.services.user.cache_set") as mock_cache_set:
        
        mock_cache_get.return_value = invalid_version_data
        mock_cache_delete.return_value = True
        mock_cache_set.return_value = True

        result = get_user(mock_db, user_id)

        assert result == mock_user
        mock_cache_get.assert_called_once()
        # Should delete invalid cache and set new one
        mock_cache_delete.assert_called_once()
        mock_cache_set.assert_called_once()

@pytest.mark.asyncio
async def test_redis_connection_failure(mock_db, mock_user):
    """Test Redis connection failure handling."""
    user_id = 1
    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    with patch("app.services.user.cache_get") as mock_cache_get, \
         patch("app.services.user.cache_set") as mock_cache_set:
        
        # Simulate Redis connection failure
        mock_cache_get.side_effect = ConnectionError("Redis connection failed")
        mock_cache_set.side_effect = ConnectionError("Redis connection failed")

        result = get_user(mock_db, user_id)

        assert result == mock_user  # Should still return correct data from DB
        mock_cache_get.assert_called_once()
        mock_cache_set.assert_not_called()  # Should not try to set cache after connection failure

@pytest.mark.asyncio
async def test_concurrent_update_conflict(mock_db_with_unique_email, mock_user):
    """Test handling of concurrent update conflicts."""
    user_id = 1
    update_data = UserUpdate(email="new@example.com")
    mock_user.email = "old@example.com"

    with patch("app.services.user.get_user") as mock_get_user, \
         patch("app.services.user.cache_delete") as mock_cache_delete, \
         patch("app.services.user.cache_set") as mock_cache_set:
        
        mock_get_user.return_value = mock_user
        mock_cache_delete.return_value = True
        mock_cache_set.return_value = True
        
        # Simulate concurrent update by raising IntegrityError
        mock_db_with_unique_email.commit.side_effect = IntegrityError(
            None, None, "Concurrent update detected"
        )

        with pytest.raises(ValueError) as exc_info:
            update_user(mock_db_with_unique_email, user_id, update_data)

        assert "Database constraint violation occurred" in str(exc_info.value)
        mock_db_with_unique_email.rollback.assert_called_once()

@pytest.mark.asyncio
async def test_cache_multi_operation_failure(mock_db, mock_user):
    """Test handling of multiple cache operation failures."""
    user_id = 1
    mock_user.email = TEST_USER_DATA["email"]

    with patch("app.services.user.get_user") as mock_get_user, \
         patch("app.services.user.cache_delete") as mock_cache_delete, \
         patch("app.services.user.cache_set") as mock_cache_set, \
         patch("app.services.user.cache_clear_pattern") as mock_cache_clear:
        
        mock_get_user.return_value = mock_user
        # Simulate all cache operations failing
        mock_cache_delete.return_value = False
        mock_cache_set.return_value = False
        mock_cache_clear.return_value = False

        result = delete_user(mock_db, user_id)

        assert result is True  # Operation should succeed despite cache failures
        mock_db.delete.assert_called_once_with(mock_user)
        mock_db.commit.assert_called_once()
        assert mock_cache_delete.call_count == 2
        mock_cache_clear.assert_called_once()

@pytest.mark.asyncio
async def test_database_deadlock_recovery(mock_db_with_unique_email, mock_user):
    """Test recovery from database deadlock during update."""
    user_id = 1
    update_data = UserUpdate(email="new@example.com")
    mock_user.email = "old@example.com"

    with patch("app.services.user.get_user") as mock_get_user:
        mock_get_user.return_value = mock_user
        
        # Simulate deadlock on first attempt, success on second
        mock_db_with_unique_email.commit.side_effect = [
            OperationalError(None, None, "Deadlock found"),
            None
        ]

        with pytest.raises(RuntimeError) as exc_info:
            update_user(mock_db_with_unique_email, user_id, update_data)

        assert "Failed to update user" in str(exc_info.value)
        assert mock_db_with_unique_email.rollback.called

@pytest.mark.asyncio
async def test_partial_cache_update_failure(mock_db, mock_user):
    """Test handling of partial cache update failures during user creation."""
    user_data = UserCreate(**TEST_USER_DATA)
    mock_db.add.return_value = None
    mock_db.commit.return_value = None
    mock_db.refresh.return_value = None
    mock_user.id = 1

    with patch("app.services.user.get_password_hash") as mock_hash, \
         patch("app.services.user.User") as mock_user_class, \
         patch("app.services.user.cache_set") as mock_cache_set, \
         patch("app.services.user.cache_clear_pattern") as mock_cache_clear:
        
        mock_hash.return_value = "hashed_password"
        mock_user_class.return_value = mock_user
        # Simulate partial cache update failure
        mock_cache_set.side_effect = [True, False]  # First succeeds, second fails
        mock_cache_clear.return_value = False

        result = create_user(mock_db, user_data)

        assert result == mock_user  # Operation should succeed despite cache failures
        assert mock_cache_set.call_count == 2
        mock_cache_clear.assert_called_once()

@pytest.mark.asyncio
async def test_database_connection_timeout(mock_db, mock_user):
    """Test handling of database connection timeout."""
    user_id = 1
    mock_db.query.side_effect = OperationalError(
        None, None, "Database connection timeout"
    )

    with patch("app.services.user.cache_get") as mock_cache_get:
        mock_cache_get.return_value = None

        with pytest.raises(OperationalError) as exc_info:
            get_user(mock_db, user_id)

        assert "Database connection timeout" in str(exc_info.value)
        mock_cache_get.assert_called_once()
        mock_db.query.assert_called_once()

@pytest.mark.asyncio
async def test_cache_data_type_mismatch(mock_db, mock_user):
    """Test handling of cache data type mismatches."""
    user_id = 1
    invalid_data = {
        "id": "not_an_integer",  # Wrong type for ID
        "email": 12345,  # Wrong type for email
        "username": ["invalid"],  # Wrong type for username
        "full_name": "Test User",
        "is_active": "not_a_boolean",  # Wrong type for is_active
        "is_superuser": False,
        "created_at": "2024-02-19T12:00:00",
        "updated_at": "2024-02-19T12:00:00",
        "_cache_version": "1.1"
    }

    mock_db.query.return_value.filter.return_value.first.return_value = mock_user

    with patch("app.services.user.cache_get") as mock_cache_get, \
         patch("app.services.user.cache_delete") as mock_cache_delete, \
         patch("app.services.user.cache_set") as mock_cache_set:
        
        mock_cache_get.return_value = invalid_data
        mock_cache_delete.return_value = True
        mock_cache_set.return_value = True

        result = get_user(mock_db, user_id)

        assert result == mock_user
        mock_cache_get.assert_called_once()
        mock_cache_delete.assert_called_once()  # Should delete invalid cache
        mock_cache_set.assert_called_once()  # Should set new cache with correct types

@pytest.mark.asyncio
async def test_transaction_isolation_violation(mock_db_with_unique_email, mock_user):
    """Test handling of transaction isolation violations."""
    user_id = 1
    update_data = UserUpdate(email="new@example.com")
    mock_user.email = "old@example.com"

    with patch("app.services.user.get_user") as mock_get_user:
        mock_get_user.return_value = mock_user
        
        # Simulate transaction isolation violation
        mock_db_with_unique_email.commit.side_effect = OperationalError(
            None, None, "Transaction isolation violation"
        )

        with pytest.raises(RuntimeError) as exc_info:
            update_user(mock_db_with_unique_email, user_id, update_data)

        assert "Failed to update user" in str(exc_info.value)
        mock_db_with_unique_email.rollback.assert_called_once()
