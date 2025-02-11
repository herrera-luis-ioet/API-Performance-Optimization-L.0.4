"""
Unit tests for Redis cache error handling scenarios.

Tests various error conditions and edge cases in the cache implementation:
- Connection failures
- Serialization errors
- Timeout scenarios
- Data corruption
- Concurrent access patterns
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from redis.exceptions import (
    ConnectionError,
    TimeoutError,
    ResponseError,
    DataError,
    RedisError
)
from app.core.cache import (
    cache_get,
    cache_set,
    cache_delete,
    cache_exists,
    cache_multi_get,
    cache_multi_set,
    check_redis_health,
    serialize_value,
    deserialize_value,
    cache_clear_pattern,
    cache_increment
)

# Test data
TEST_KEY = "test_key"
TEST_VALUE = {"name": "test", "value": 123}
TEST_KEYS = ["key1", "key2", "key3"]
TEST_DATA = {
    "key1": {"value": 1},
    "key2": {"value": 2},
    "key3": {"value": 3}
}

@pytest.fixture
def mock_redis():
    """Fixture to provide a mock Redis client"""
    with patch("app.core.cache.Redis") as mock:
        yield mock

def test_connection_error(mock_redis):
    """Test handling of Redis connection errors"""
    mock_redis.return_value.get.side_effect = ConnectionError("Connection refused")
    
    with pytest.raises(RedisError):
        cache_get(TEST_KEY)

def test_timeout_error(mock_redis):
    """Test handling of Redis timeout errors"""
    mock_redis.return_value.get.side_effect = TimeoutError("Operation timed out")
    
    with pytest.raises(RedisError):
        cache_get(TEST_KEY)

def test_response_error(mock_redis):
    """Test handling of Redis response errors"""
    mock_redis.return_value.get.side_effect = ResponseError("Invalid response")
    
    with pytest.raises(RedisError):
        cache_get(TEST_KEY)

def test_data_error(mock_redis):
    """Test handling of Redis data errors"""
    mock_redis.return_value.get.side_effect = DataError("Invalid data format")
    
    with pytest.raises(RedisError):
        cache_get(TEST_KEY)

def test_serialization_error():
    """Test handling of value serialization errors"""
    # Create an object that can't be JSON serialized
    class UnserializableObject:
        pass
    
    with pytest.raises(ValueError):
        serialize_value(UnserializableObject())

def test_deserialization_error():
    """Test handling of value deserialization errors"""
    invalid_json = "{'invalid': json}"
    
    with pytest.raises(ValueError):
        deserialize_value(invalid_json)

def test_health_check_failure(mock_redis):
    """Test Redis health check failure handling"""
    mock_redis.return_value.ping.side_effect = ConnectionError("Connection refused")
    
    assert check_redis_health() is False

def test_cache_set_serialization_error(mock_redis):
    """Test cache set with unserializable data"""
    class UnserializableObject:
        pass
    
    result = cache_set(TEST_KEY, UnserializableObject())
    assert result is False

def test_cache_multi_get_partial_failure(mock_redis):
    """Test multi-get with some corrupted values"""
    mock_redis.return_value.mget.return_value = [
        json.dumps({"valid": "data"}),
        "invalid json",
        json.dumps({"more": "data"})
    ]
    
    result = cache_multi_get(TEST_KEYS)
    assert len(result) == 2  # Only valid JSON values should be included
    assert "key2" not in result  # Corrupted value should be skipped

def test_cache_multi_set_partial_failure(mock_redis):
    """Test multi-set with some unserializable values"""
    data = {
        "key1": {"valid": "data"},
        "key2": object(),  # Unserializable
        "key3": {"more": "data"}
    }
    
    mock_pipeline = MagicMock()
    mock_redis.return_value.pipeline.return_value = mock_pipeline
    mock_pipeline.execute.return_value = [True, True]
    
    result = cache_multi_set(data)
    assert result is True  # Operation should succeed for serializable values

def test_cache_clear_pattern_empty(mock_redis):
    """Test clear pattern with no matching keys"""
    mock_redis.return_value.keys.return_value = []
    
    result = cache_clear_pattern("nonexistent:*")
    assert result is True

def test_cache_clear_pattern_error(mock_redis):
    """Test clear pattern with Redis error"""
    mock_redis.return_value.keys.side_effect = RedisError("Operation failed")
    
    result = cache_clear_pattern("test:*")
    assert result is False

def test_cache_increment_invalid_value(mock_redis):
    """Test increment with non-numeric value"""
    mock_redis.return_value.incrby.side_effect = ResponseError("Value is not an integer")
    
    result = cache_increment(TEST_KEY)
    assert result is None

def test_concurrent_access_simulation(mock_redis):
    """Simulate concurrent access patterns"""
    # Simulate race condition with pipeline
    mock_pipeline = MagicMock()
    mock_redis.return_value.pipeline.return_value = mock_pipeline
    mock_pipeline.execute.side_effect = [
        ConnectionError("Connection lost during transaction"),
        [True, True, True]  # Second attempt succeeds
    ]
    
    data = {k: TEST_DATA[k] for k in TEST_KEYS}
    result = cache_multi_set(data)
    assert result is False  # First attempt fails
    
    result = cache_multi_set(data)
    assert result is True  # Second attempt succeeds
