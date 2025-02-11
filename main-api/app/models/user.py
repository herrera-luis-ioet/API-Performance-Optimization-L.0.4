"""
User model definition.
"""

from sqlalchemy import Column, String, Boolean
from sqlalchemy.sql.sqltypes import Integer

from app.models.base import BaseModel


class User(BaseModel):
    """User model for storing user information."""
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100))
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)