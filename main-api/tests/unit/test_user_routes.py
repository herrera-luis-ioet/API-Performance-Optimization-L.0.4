"""
Unit tests for user routes with focus on edge cases and error handling.
"""

import pytest
from fastapi import status
from typing import Dict, Any

# Test data
VALID_USER_DATA = {
    "email": "test@example.com",
    "username": "testuser",
    "password": "testpass123",
    "full_name": "Test User",
    "is_active": True,
    "is_superuser": False
}

@pytest.fixture
def valid_user(client) -> Dict[str, Any]:
    """Create a valid user for testing."""
    response = client.post("/users/", json=VALID_USER_DATA)
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()

class TestUserCreation:
    """Test cases for user creation endpoint."""

    def test_create_valid_user(self, client):
        """Test creating a user with valid data."""
        response = client.post("/users/", json=VALID_USER_DATA)
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["email"] == VALID_USER_DATA["email"]
        assert data["username"] == VALID_USER_DATA["username"]
        assert "id" in data
        assert "password" not in data

    def test_create_duplicate_user(self, client, valid_user):
        """Test creating a user with duplicate email."""
        response = client.post("/users/", json=VALID_USER_DATA)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already exists" in response.json()["detail"].lower()

    @pytest.mark.parametrize("field", ["email", "username", "password"])
    def test_missing_required_fields(self, client, field):
        """Test creating a user with missing required fields."""
        data = VALID_USER_DATA.copy()
        del data[field]
        response = client.post("/users/", json=data)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_invalid_email_format(self, client):
        """Test creating a user with invalid email format."""
        data = VALID_USER_DATA.copy()
        data["email"] = "invalid-email"
        response = client.post("/users/", json=data)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_short_username(self, client):
        """Test creating a user with too short username."""
        data = VALID_USER_DATA.copy()
        data["username"] = "ab"  # min_length is 3
        response = client.post("/users/", json=data)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_long_username(self, client):
        """Test creating a user with too long username."""
        data = VALID_USER_DATA.copy()
        data["username"] = "a" * 51  # max_length is 50
        response = client.post("/users/", json=data)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_short_password(self, client):
        """Test creating a user with too short password."""
        data = VALID_USER_DATA.copy()
        data["password"] = "short"  # min_length is 8
        response = client.post("/users/", json=data)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_special_characters_in_username(self, client):
        """Test creating a user with special characters in username."""
        data = VALID_USER_DATA.copy()
        data["username"] = "test@user#123"
        response = client.post("/users/", json=data)
        assert response.status_code == status.HTTP_201_CREATED

class TestUserRetrieval:
    """Test cases for user retrieval endpoints."""

    def test_get_existing_user(self, client, valid_user):
        """Test retrieving an existing user."""
        response = client.get(f"/users/{valid_user['id']}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == valid_user

    def test_get_nonexistent_user(self, client):
        """Test retrieving a non-existent user."""
        response = client.get("/users/99999")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_users_pagination(self, client):
        """Test user list pagination."""
        # Create multiple users
        for i in range(5):
            data = VALID_USER_DATA.copy()
            data["email"] = f"test{i}@example.com"
            data["username"] = f"testuser{i}"
            client.post("/users/", json=data)

        # Test pagination
        response = client.get("/users/?skip=0&limit=3")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 3

        response = client.get("/users/?skip=3&limit=3")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 2

    def test_invalid_pagination_params(self, client):
        """Test invalid pagination parameters."""
        # Test negative skip
        response = client.get("/users/?skip=-1")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Test zero limit
        response = client.get("/users/?limit=0")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # Test exceeding max limit
        response = client.get("/users/?limit=101")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

class TestUserUpdate:
    """Test cases for user update endpoint."""

    def test_update_valid_user(self, client, valid_user):
        """Test updating a user with valid data."""
        update_data = {
            "email": "updated@example.com",
            "username": "updateduser"
        }
        response = client.put(f"/users/{valid_user['id']}", json=update_data)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["email"] == update_data["email"]
        assert data["username"] == update_data["username"]

    def test_update_nonexistent_user(self, client):
        """Test updating a non-existent user."""
        response = client.put("/users/99999", json={"username": "newname"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_with_existing_email(self, client, valid_user):
        """Test updating a user with an email that already exists."""
        # Create another user
        other_data = VALID_USER_DATA.copy()
        other_data["email"] = "other@example.com"
        other_data["username"] = "otheruser"
        other_user = client.post("/users/", json=other_data).json()

        # Try to update with existing email
        update_data = {"email": VALID_USER_DATA["email"]}
        response = client.put(f"/users/{other_user['id']}", json=update_data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_partial_update(self, client, valid_user):
        """Test partial update of user data."""
        update_data = {"full_name": "Updated Name"}
        response = client.put(f"/users/{valid_user['id']}", json=update_data)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["full_name"] == update_data["full_name"]
        assert response.json()["email"] == valid_user["email"]

class TestUserDeletion:
    """Test cases for user deletion endpoint."""

    def test_delete_existing_user(self, client, valid_user):
        """Test deleting an existing user."""
        response = client.delete(f"/users/{valid_user['id']}")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify user is deleted
        get_response = client.get(f"/users/{valid_user['id']}")
        assert get_response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_nonexistent_user(self, client):
        """Test deleting a non-existent user."""
        response = client.delete("/users/99999")
        assert response.status_code == status.HTTP_404_NOT_FOUND

class TestRequestSizeAndFormat:
    """Test cases for request size limits and malformed requests."""

    def test_large_request_body(self, client):
        """Test request with large body."""
        data = VALID_USER_DATA.copy()
        data["full_name"] = "x" * 1000  # Very long name
        response = client.post("/users/", json=data)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_malformed_json(self, client):
        """Test handling of malformed JSON request."""
        response = client.post(
            "/users/",
            headers={"Content-Type": "application/json"},
            content="invalid json content"
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY