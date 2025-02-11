"""
User service for handling user-related operations with Redis caching.
"""

import logging
import contextlib
from functools import wraps
from typing import List, Optional, Dict, Callable, TypeVar, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError
from redis import RedisError

from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.core.security import get_password_hash
from app.core.cache import (
    cache_get, cache_set, cache_delete, 
    cache_multi_get, cache_multi_set,
    cache_clear_pattern
)

# Type variable for generic function return type
T = TypeVar('T')

# Configure logging
logger = logging.getLogger(__name__)

# Cache key patterns
USER_KEY = "user:{}"  # Format: user:123 - Primary user cache key
USER_EMAIL_KEY = "user:email:{}"  # Format: user:email:test@example.com - Secondary lookup key
USERS_LIST_KEY = "users:list:{}:{}"  # Format: users:list:0:100 - Paginated list cache key

# Cache expiration times (in seconds)
USER_CACHE_EXPIRE = 3600  # 1 hour - matches requirement for user data
USERS_LIST_CACHE_EXPIRE = 300  # 5 minutes - shorter for list data to prevent stale pagination

# Transaction retry settings
MAX_RETRIES = 3
RETRY_BACKOFF = 0.1  # seconds

@contextlib.contextmanager
def transaction_context(db: Session, nested: bool = False):
    """
    Context manager for handling database transactions with proper savepoint management.
    
    Args:
        db: Database session
        nested: Whether to use a nested transaction (savepoint)
    """
    if nested and db.in_transaction():
        with db.begin_nested() as savepoint:
            try:
                yield savepoint
            except Exception:
                savepoint.rollback()
                raise
    else:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

def with_transaction_retry(func: Callable[..., T]) -> Callable[..., T]:
    """
    Decorator for retrying database operations on deadlock or lock timeout.
    
    Args:
        func: Function to wrap with retry logic
        
    Returns:
        Wrapped function with retry logic
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        retries = 0
        while True:
            try:
                return func(*args, **kwargs)
            except OperationalError as e:
                if retries >= MAX_RETRIES or "deadlock" not in str(e).lower():
                    raise
                retries += 1
                logger.warning(f"Deadlock detected, retry {retries}/{MAX_RETRIES}")
                import time
                time.sleep(RETRY_BACKOFF * retries)
    return wrapper

def _user_to_dict(user: User) -> Dict:
    """
    Convert User model to dictionary for caching.
    
    Args:
        user: User model instance
        
    Returns:
        Dict: User data dictionary
    """
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "created_at": str(user.created_at),
        "updated_at": str(user.updated_at),
        "_cache_version": "1.1"  # Cache version for validation - updated for improved error handling
    }

def _validate_cache_data(data: Dict) -> bool:
    """
    Validate cached user data.
    
    Args:
        data: Cached user data dictionary
        
    Returns:
        bool: True if data is valid, False otherwise
    """
    required_fields = {
        "id", "email", "username", "full_name", "is_active", 
        "is_superuser", "created_at", "updated_at", "_cache_version"
    }
    
    try:
        # Check if all required fields are present
        if not all(field in data for field in required_fields):
            return False
            
        # Validate data types
        if not isinstance(data["id"], int):
            return False
        if not isinstance(data["email"], str):
            return False
        if not isinstance(data["username"], str):
            return False
        if not isinstance(data["_cache_version"], str):
            return False
            
        # Validate version - accept both current and previous versions
        if data["_cache_version"] not in ["1.0", "1.1"]:
            return False
            
        return True
    except (TypeError, KeyError):
        return False


# PUBLIC_INTERFACE
@with_transaction_retry
def create_user(db: Session, user_data: UserCreate) -> User:
    """
    Create a new user and cache the result.

    Args:
        db: Database session
        user_data: User data for creation

    Returns:
        User: Created user object

    Raises:
        ValueError: If user with same email or username already exists, with specific error messages
        RuntimeError: If cache operations fail
    """
    try:
        with transaction_context(db) as tx:
            # Validate email uniqueness with case-insensitive check
            existing_email_user = db.query(User).filter(
                User.email.ilike(user_data.email)
            ).first()
            if existing_email_user:
                raise ValueError(
                    f"Email address '{user_data.email}' is already registered. "
                    "Please use a different email address or try logging in."
                )

            # Validate username uniqueness
            existing_username_user = db.query(User).filter(
                User.username == user_data.username
            ).first()
            if existing_username_user:
                raise ValueError(
                    f"Username '{user_data.username}' is already taken. "
                    "Please choose a different username."
                )

            # Create user in database with validated data
            hashed_password = get_password_hash(user_data.password)
            db_user = User(
                email=user_data.email.lower(),  # Store email in lowercase for consistency
                username=user_data.username,
                hashed_password=hashed_password,
                full_name=user_data.full_name,
                is_active=user_data.is_active,
                is_superuser=user_data.is_superuser
            )
            db.add(db_user)
            
            # Cache the new user data with proper error handling
            try:
                # Convert user to cacheable format
                user_dict = _user_to_dict(db_user)
                
                # Set primary user cache with specified key format and expiration
                # Using key='user:{id}' format and 3600s expiration as required
                if not cache_set(USER_KEY.format(db_user.id), user_dict, USER_CACHE_EXPIRE):
                    logger.warning(f"Failed to set primary cache for user {db_user.id}")
                
                # Set email lookup cache as a secondary index
                if not cache_set(USER_EMAIL_KEY.format(db_user.email), user_dict, USER_CACHE_EXPIRE):
                    logger.warning(f"Failed to set email lookup cache for user {db_user.email}")
                
                # Invalidate users list cache to ensure fresh data
                if not cache_clear_pattern(USERS_LIST_KEY.format("*", "*")):
                    logger.warning("Failed to invalidate users list cache")
                
            except (RedisError, ValueError) as e:
                # Log cache errors but don't block user creation
                # This ensures cache operations don't affect main database flow
                logger.warning(f"Cache operations failed during user creation: {e}")
            
            return db_user
            
    except IntegrityError as e:
        db.rollback()
        # Provide more specific error message based on the constraint violation
        if "email" in str(e).lower():
            raise ValueError(f"User with email {user_data.email} already exists")
        elif "username" in str(e).lower():
            raise ValueError(f"User with username {user_data.username} already exists")
        else:
            raise ValueError("User with this email or username already exists")


# PUBLIC_INTERFACE
def get_user(db: Session, user_id: int) -> Optional[User]:
    """
    Get user by ID with caching.

    Args:
        db: Database session
        user_id: User ID

    Returns:
        Optional[User]: User object if found, None otherwise
    """
    # Try to get from cache first
    cache_key = USER_KEY.format(user_id)
    cached_user = None
    redis_available = True
    try:
        cached_user = cache_get(cache_key)
    except (RedisError, ConnectionError) as e:
        logger.error(f"Redis error while getting user {user_id}: {e}")
        redis_available = False
        
    if cached_user:
        # Validate cache data structure and version
        if _validate_cache_data(cached_user):
            try:
                # Remove cache version before converting to User model
                cached_data = {k: v for k, v in cached_user.items() if k != "_cache_version"}
                return User(**cached_data)
            except (TypeError, ValueError) as e:
                logger.error(f"Failed to deserialize cached user {user_id}: {e}")
        else:
            logger.warning(f"Invalid cache data structure for user {user_id}")
            
        try:
            # Cache is invalid or corrupted, delete it
            cache_delete(cache_key)
            logger.info(f"Deleted invalid cache for user {user_id}")
        except (RedisError, ConnectionError) as e:
            logger.error(f"Failed to delete corrupted cache for user {user_id}: {e}")
        
    # If not in cache or cache failed, get from database
    db_user = db.query(User).filter(User.id == user_id).first()
    if db_user and redis_available:
        # Only attempt to cache if Redis was available
        user_dict = _user_to_dict(db_user)
        try:
            cache_set(cache_key, user_dict, USER_CACHE_EXPIRE)
        except (RedisError, ConnectionError) as e:
            logger.error(f"Failed to cache user {user_id}: {e}")
            redis_available = False
        
    return db_user


# PUBLIC_INTERFACE
def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """
    Get user by email with caching.

    Args:
        db: Database session
        email: User email

    Returns:
        Optional[User]: User object if found, None otherwise
    """
    # Try to get from cache first
    cache_key = USER_EMAIL_KEY.format(email)
    try:
        cached_user = cache_get(cache_key)
        if cached_user:
            try:
                # Convert cached dict back to User model
                return User(**cached_user)
            except (TypeError, ValueError) as e:
                logger.error(f"Failed to deserialize cached user with email {email}: {e}")
                # Cache is corrupted, delete it
                cache_delete(cache_key)
    except RedisError as e:
        logger.error(f"Redis error while getting user by email {email}: {e}")
        
    # If not in cache or cache failed, get from database
    db_user = db.query(User).filter(User.email == email).first()
    if db_user:
        try:
            # Cache the user data
            user_dict = _user_to_dict(db_user)
            cache_success = True
            
            if not cache_set(cache_key, user_dict, USER_CACHE_EXPIRE):
                logger.error(f"Failed to cache user by email {email}")
                cache_success = False
                
            if not cache_set(USER_KEY.format(db_user.id), user_dict, USER_CACHE_EXPIRE):
                logger.error(f"Failed to cache user by ID {db_user.id}")
                cache_success = False
                
            if not cache_success:
                logger.warning("Some cache operations failed during user lookup by email")
        except (RedisError, ValueError) as e:
            logger.error(f"Failed to cache user with email {email}: {e}")
        
    return db_user


# PUBLIC_INTERFACE
def get_users(db: Session, skip: int = 0, limit: int = 100) -> List[User]:
    """
    Get list of users with pagination and caching.

    Args:
        db: Database session
        skip: Number of records to skip
        limit: Maximum number of records to return

    Returns:
        List[User]: List of user objects

    Raises:
        ValueError: If skip is negative or limit is not positive
    """
    if skip < 0:
        raise ValueError("skip must be non-negative")
    if limit <= 0:
        raise ValueError("limit must be positive")
    # Try to get from cache first
    cache_key = USERS_LIST_KEY.format(skip, limit)
    try:
        cached_users = cache_get(cache_key)
        if cached_users:
            try:
                # Convert cached dict list back to User models
                return [User(**user_data) for user_data in cached_users]
            except (TypeError, ValueError) as e:
                logger.error(f"Failed to deserialize cached users list: {e}")
                # Cache is corrupted, delete it
                cache_delete(cache_key)
    except RedisError as e:
        logger.error(f"Redis error while getting users list: {e}")
        
    # If not in cache or cache failed, get from database
    db_users = db.query(User).offset(skip).limit(limit).all()
    if db_users:
        try:
            # Cache individual users and the list
            users_data = [_user_to_dict(user) for user in db_users]
            cache_success = True
            
            if not cache_set(cache_key, users_data, USERS_LIST_CACHE_EXPIRE):
                logger.error("Failed to cache users list")
                cache_success = False
            
            # Cache individual users
            user_cache_data = {
                USER_KEY.format(user.id): _user_to_dict(user)
                for user in db_users
            }
            if not cache_multi_set(user_cache_data, USER_CACHE_EXPIRE):
                logger.error("Failed to cache individual users")
                cache_success = False
                
            if not cache_success:
                logger.warning("Some cache operations failed during users list retrieval")
        except (RedisError, ValueError) as e:
            logger.error(f"Failed to cache users list: {e}")
        
    return db_users


# PUBLIC_INTERFACE
@with_transaction_retry
def update_user(db: Session, user_id: int, user_data: UserUpdate) -> Optional[User]:
    """
    Update user information with cache invalidation.

    Args:
        db: Database session
        user_id: User ID
        user_data: User data for update

    Returns:
        Optional[User]: Updated user object if found, None otherwise

    Raises:
        ValueError: If update would create duplicate email or username
        RuntimeError: If database transaction fails
        IntegrityError: If database constraints are violated
    """
    db_user = get_user(db, user_id)
    if not db_user:
        logger.warning(f"User not found for update: {user_id}")
        return None

    # Store old email for cache invalidation
    old_email = db_user.email

    update_data = user_data.model_dump(exclude_unset=True)
    if "password" in update_data:
        update_data["hashed_password"] = get_password_hash(update_data.pop("password"))

    with transaction_context(db) as tx:
        logger.info(f"Starting transaction for user update {user_id}")
        
        # Use nested transaction for validation
        with transaction_context(db, nested=True):
            # Validate unique constraints before update
            if "email" in update_data and update_data["email"] != old_email:
                existing_user = db.query(User).filter(
                    User.email == update_data["email"],
                    User.id != user_id
                ).first()
                if existing_user:
                    raise ValueError(f"Email {update_data['email']} is already in use")

            if "username" in update_data:
                existing_user = db.query(User).filter(
                    User.username == update_data["username"],
                    User.id != user_id
                ).first()
                if existing_user:
                    raise ValueError(f"Username {update_data['username']} is already in use")

        # Apply updates
        for field, value in update_data.items():
            setattr(db_user, field, value)

        # Cache operations with error handling and versioning
        cache_success = True
        try:
            # Invalidate old caches with retries
            for _ in range(2):  # Retry once on failure
                if cache_delete(USER_KEY.format(user_id)):
                    break
                logger.warning(f"Retrying cache deletion for user ID {user_id}")
            else:
                logger.error(f"Failed to delete old user cache for ID {user_id}")
                cache_success = False
                
            for _ in range(2):  # Retry once on failure
                if cache_delete(USER_EMAIL_KEY.format(old_email)):
                    break
                logger.warning(f"Retrying cache deletion for email {old_email}")
            else:
                logger.error(f"Failed to delete old user cache for email {old_email}")
                cache_success = False
            
            # Set new cache with versioning
            user_dict = _user_to_dict(db_user)  # Contains updated cache version
            if not cache_set(USER_KEY.format(user_id), user_dict, USER_CACHE_EXPIRE):
                logger.error(f"Failed to set new user cache for ID {user_id}")
                cache_success = False
                
            if not cache_set(USER_EMAIL_KEY.format(db_user.email), user_dict, USER_CACHE_EXPIRE):
                logger.error(f"Failed to set new user cache for email {db_user.email}")
                cache_success = False
            
            # Invalidate users list cache
            if not cache_clear_pattern(USERS_LIST_KEY.format("*", "*")):
                logger.error("Failed to invalidate users list cache")
                cache_success = False
                
            if not cache_success:
                logger.warning("Some cache operations failed during user update - data may be stale")
                
        except RedisError as e:
            logger.error(f"Redis error during user update: {e}")
            logger.warning("Continuing with database update despite cache errors")
        
        return db_user


# PUBLIC_INTERFACE
@with_transaction_retry
def delete_user(db: Session, user_id: int) -> bool:
    """
    Delete user by ID and clear cache.

    Args:
        db: Database session
        user_id: User ID

    Returns:
        bool: True if user was deleted, False if user was not found
    """
    db_user = get_user(db, user_id)
    if not db_user:
        return False

    # Store email for cache invalidation
    email = db_user.email

    with transaction_context(db) as tx:
        db.delete(db_user)

    # Cache operations with error handling
    cache_success = True
    try:
        # Clear user caches
        if not cache_delete(USER_KEY.format(user_id)):
            logger.error(f"Failed to delete user cache for ID {user_id}")
            cache_success = False
            
        if not cache_delete(USER_EMAIL_KEY.format(email)):
            logger.error(f"Failed to delete user cache for email {email}")
            cache_success = False
        
        # Invalidate users list cache
        if not cache_clear_pattern(USERS_LIST_KEY.format("*", "*")):
            logger.error("Failed to invalidate users list cache")
            cache_success = False
            
        if not cache_success:
            logger.warning("Some cache operations failed during user deletion")
            
    except RedisError as e:
        logger.error(f"Redis error during user deletion: {e}")
    
    return True
