"""
Main application entry point.
"""

from app import app

# Import routes here
# Example: from app.routes import items, users

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
