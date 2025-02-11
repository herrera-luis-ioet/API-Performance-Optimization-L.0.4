"""
User schema definitions for request/response handling.
"""

from typing import Optional

from pydantic import BaseModel, EmailStr, Field, ConfigDict

from app.schemas.base import BaseDBSchema, BaseCreateSchema, BaseUpdateSchema


class UserBase(BaseModel):
    """Base schema for user data."""
    
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    full_name: Optional[str] = Field(None, max_length=100)
    is_active: bool = True
    is_superuser: bool = False
    
    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseCreateSchema, UserBase):
    """Schema for creating a new user."""
    
    password: str = Field(..., min_length=8)


class UserUpdate(BaseUpdateSchema, UserBase):
    """Schema for updating an existing user."""
    
    email: Optional[EmailStr] = None
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    password: Optional[str] = Field(None, min_length=8)


class UserInDB(BaseDBSchema, UserBase):
    """Schema for user data as stored in database."""
    
    hashed_password: str


class UserResponse(BaseDBSchema, UserBase):
    """Schema for user data in responses."""
    pass
