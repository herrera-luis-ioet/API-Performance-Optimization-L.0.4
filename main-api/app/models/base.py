"""
Base model configuration and common model utilities.
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Column, DateTime
from sqlalchemy.ext.declarative import declared_attr

from app.core.database import Base

UTC = ZoneInfo("UTC")


class BaseModel(Base):
    """Base model class with common fields and utilities."""
    
    __abstract__ = True

    @declared_attr
    def __tablename__(cls) -> str:
        """Generate table name automatically based on class name."""
        return cls.__name__.lower()

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False
    )

    def dict(self) -> dict[str, Any]:
        """Convert model instance to dictionary."""
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }
