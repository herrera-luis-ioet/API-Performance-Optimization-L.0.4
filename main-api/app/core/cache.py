"""
Redis cache configuration and utilities.

This module provides a Redis connection pool and cache utilities for efficient
data caching with proper error handling and connection management.
"""

from typing import Any, Optional, List, Dict
import json
import logging
from contextlib import contextmanager
from redis import Redis, ConnectionPool, ConnectionError, RedisError, TimeoutError
from redis.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ResponseError, DataError

from .config import settings

# Cache key templates
USER_KEY = "user:{}"  # Format with user ID

# Configure logging
logger = logging.getLogger(__name__)

# Redis connection retry strategy with enhanced backoff
retry_strategy = Retry(
    ExponentialBackoff(
        cap=10,  # Maximum backoff time in seconds
        base=1.5  # Base multiplier for backoff
    ),
    retries=5,  # Increased number of retries
    supported_errors={
        ConnectionError,
        TimeoutError,
        ResponseError
    }
)

def check_redis_health() -> bool:
    """
    Check Redis connection health.
    
    Returns:
        bool: True if Redis is healthy, False otherwise
    """
    try:
        with get_redis_client() as client:
            return bool(client.ping())
    except RedisError as e:
        logger.error(f"Redis health check failed: {e}")
        return False

# Create Redis connection pool with optimized settings
redis_pool = ConnectionPool(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=settings.REDIS_DB,
    decode_responses=True,
    max_connections=10,
    socket_timeout=5,
    socket_connect_timeout=5,
    retry_on_timeout=True,
    health_check_interval=30
)

@contextmanager
def get_redis_client() -> Redis:
    """
    Get Redis client instance with automatic connection management.
    
    Yields:
        Redis: Redis client instance
    
    Raises:
        RedisError: If connection fails
    """
    client = None
    try:
        client = Redis(
            connection_pool=redis_pool,
            retry=retry_strategy
        )
        yield client
    except ConnectionError as e:
        logger.error(f"Redis connection error: {e}", exc_info=True)
        logger.info("Attempting to reconnect with retry strategy...")
        raise
    except TimeoutError as e:
        logger.error(f"Redis timeout error: {e}", exc_info=True)
        logger.info("Operation timed out, will retry with backoff...")
        raise
    except ResponseError as e:
        logger.error(f"Redis response error: {e}", exc_info=True)
        raise
    except DataError as e:
        logger.error(f"Redis data error: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Unexpected Redis error: {e}", exc_info=True)
        raise
    finally:
        if client:
            client.close()

def serialize_value(value: Any) -> str:
    """
    Serialize value to JSON string.
    
    Args:
        value: Value to serialize
        
    Returns:
        str: JSON string
        
    Raises:
        ValueError: If value cannot be serialized
    """
    try:
        return json.dumps(value)
    except (TypeError, ValueError) as e:
        logger.error(f"Failed to serialize value: {e}")
        raise ValueError(f"Could not serialize value: {e}")

def deserialize_value(value: str) -> Any:
    """
    Deserialize JSON string to value.
    
    Args:
        value: JSON string to deserialize
        
    Returns:
        Any: Deserialized value
        
    Raises:
        ValueError: If value cannot be deserialized
    """
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to deserialize value: {e}")
        raise ValueError(f"Could not deserialize value: {e}")

# PUBLIC_INTERFACE
def cache_get(key: str) -> Optional[Any]:
    """
    Get value from cache.
    
    Args:
        key: Cache key
        
    Returns:
        Any: Cached value or None if not found
        
    Raises:
        RedisError: If Redis operation fails
    """
    with get_redis_client() as client:
        try:
            value = client.get(key)
            return deserialize_value(value) if value else None
        except RedisError as e:
            logger.error(f"Failed to get cache key {key}: {e}")
            raise

# PUBLIC_INTERFACE
def cache_set(key: str, value: Any, expire: int = 3600) -> bool:
    """
    Set value in cache.
    
    Args:
        key: Cache key
        value: Value to cache
        expire: Expiration time in seconds (default: 1 hour)
        
    Returns:
        bool: True if successful, False otherwise
        
    Raises:
        RedisError: If Redis operation fails
        ValueError: If value cannot be serialized
    """
    with get_redis_client() as client:
        try:
            serialized = serialize_value(value)
            return bool(client.setex(key, expire, serialized))
        except (RedisError, ValueError) as e:
            logger.error(f"Failed to set cache key {key}: {e}")
            return False

# PUBLIC_INTERFACE
def cache_delete(key: str) -> bool:
    """
    Delete value from cache.
    
    Args:
        key: Cache key
        
    Returns:
        bool: True if successful, False otherwise
        
    Raises:
        RedisError: If Redis operation fails
    """
    with get_redis_client() as client:
        try:
            return bool(client.delete(key))
        except RedisError as e:
            logger.error(f"Failed to delete cache key {key}: {e}")
            return False

# PUBLIC_INTERFACE
def cache_exists(key: str) -> bool:
    """
    Check if key exists in cache.
    
    Args:
        key: Cache key
        
    Returns:
        bool: True if key exists, False otherwise
        
    Raises:
        RedisError: If Redis operation fails
    """
    with get_redis_client() as client:
        try:
            return bool(client.exists(key))
        except RedisError as e:
            logger.error(f"Failed to check cache key {key}: {e}")
            return False

# PUBLIC_INTERFACE
def cache_multi_get(keys: List[str]) -> Dict[str, Any]:
    """
    Get multiple values from cache.
    
    Args:
        keys: List of cache keys
        
    Returns:
        Dict[str, Any]: Dictionary of key-value pairs for found keys
        
    Raises:
        RedisError: If Redis operation fails
    """
    with get_redis_client() as client:
        try:
            values = client.mget(keys)
            result = {}
            for key, value in zip(keys, values):
                if value is not None:
                    try:
                        result[key] = deserialize_value(value)
                    except ValueError:
                        continue
            return result
        except RedisError as e:
            logger.error(f"Failed to get multiple cache keys: {e}")
            raise

# PUBLIC_INTERFACE
def cache_multi_set(data: Dict[str, Any], expire: int = 3600) -> bool:
    """
    Set multiple values in cache.
    
    Args:
        data: Dictionary of key-value pairs to cache
        expire: Expiration time in seconds (default: 1 hour)
        
    Returns:
        bool: True if all operations successful, False otherwise
        
    Raises:
        RedisError: If Redis operation fails
    """
    with get_redis_client() as client:
        try:
            pipeline = client.pipeline()
            for key, value in data.items():
                try:
                    serialized = serialize_value(value)
                    pipeline.setex(key, expire, serialized)
                except ValueError:
                    continue
            results = pipeline.execute()
            return all(results)
        except RedisError as e:
            logger.error(f"Failed to set multiple cache keys: {e}")
            return False

# PUBLIC_INTERFACE
def cache_increment(key: str, amount: int = 1) -> Optional[int]:
    """
    Increment counter in cache.
    
    Args:
        key: Cache key
        amount: Amount to increment (default: 1)
        
    Returns:
        Optional[int]: New value or None if operation failed
        
    Raises:
        RedisError: If Redis operation fails
    """
    with get_redis_client() as client:
        try:
            return client.incrby(key, amount)
        except RedisError as e:
            logger.error(f"Failed to increment cache key {key}: {e}")
            return None

# PUBLIC_INTERFACE
def cache_clear_pattern(pattern: str) -> bool:
    """
    Delete all keys matching pattern.
    
    Args:
        pattern: Pattern to match (e.g., "user:*")
        
    Returns:
        bool: True if successful, False otherwise
        
    Raises:
        RedisError: If Redis operation fails
    """
    with get_redis_client() as client:
        try:
            keys = client.keys(pattern)
            if keys:
                return bool(client.delete(*keys))
            return True
        except RedisError as e:
            logger.error(f"Failed to clear cache pattern {pattern}: {e}")
            return False
