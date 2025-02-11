"""
Core configuration module for the application.
Handles environment variables and application settings.
"""

from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings."""
    
    # API Settings
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "API Performance Optimization"
    
    # Database Settings
    DB_TYPE: str = "mysql"  # Options: mysql, sqlite
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "user"
    MYSQL_PASSWORD: str = "password"
    MYSQL_DB: str = "api_performance_db"
    SQLITE_DB: str = "test.db"  # SQLite database file name
    
    # Redis Settings
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_TEST_DB: int = 1  # Separate database for testing
    
    model_config = ConfigDict(
        case_sensitive=True,
        env_file=".env"
    )


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    
    Returns:
        Settings: Application settings instance
    """
    return Settings()


# Export settings instance
settings = get_settings()
