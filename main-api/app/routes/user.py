"""
User API endpoints.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services import user as user_service
from app.schemas.user import UserCreate, UserUpdate, UserResponse


router = APIRouter(prefix="/users", tags=["users"])


@router.post("/", response_model=UserResponse, status_code=201)
def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db)
) -> UserResponse:
    """Create new user."""
    try:
        return user_service.create_user(db, user_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db)
) -> UserResponse:
    """Get user by ID."""
    db_user = user_service.get_user(db, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user


@router.get("/", response_model=List[UserResponse])
def get_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db)
) -> List[UserResponse]:
    """Get list of users with pagination."""
    return user_service.get_users(db, skip=skip, limit=limit)


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    user_data: UserUpdate,
    db: Session = Depends(get_db)
) -> UserResponse:
    """Update user information."""
    try:
        db_user = user_service.update_user(db, user_id, user_data)
        if not db_user:
            raise HTTPException(status_code=404, detail="User not found")
        return db_user
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db)
) -> None:
    """Delete user."""
    if not user_service.delete_user(db, user_id):
        raise HTTPException(status_code=404, detail="User not found")
