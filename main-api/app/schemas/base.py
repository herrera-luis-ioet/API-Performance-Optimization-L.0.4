"""
Base Pydantic schemas and common schema utilities.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class BaseSchema(BaseModel):
    """Base schema with common configuration."""
    
    model_config = ConfigDict(from_attributes=True)


class BaseDBSchema(BaseSchema):
    """Base schema for database models with common fields."""
    
    id: int
    created_at: datetime
    updated_at: datetime


class BaseCreateSchema(BaseSchema):
    """Base schema for creating new records."""
    pass


class BaseUpdateSchema(BaseSchema):
    """Base schema for updating existing records."""
    pass