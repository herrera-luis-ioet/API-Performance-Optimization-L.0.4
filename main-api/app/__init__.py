"""
Main application package initialization.
This package contains the FastAPI application and all its components.
"""

from fastapi import FastAPI
from app.routes import user

app = FastAPI(
    title="API Performance Optimization",
    description="A FastAPI application focused on performance optimization",
    version="0.1.0"
)

# Include routers
app.include_router(user.router)
