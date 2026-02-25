import pytest
import json
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.deps import get_db
from app.db.models.user import User
from app.auth.hashing import hash_password
import uuid


class TestAuth:
    """Test authentication routes."""
    
    def test_login_invalid_credentials_returns_303(self, client, clear_users, mock_db):
        """Test login with invalid credentials returns redirect."""
        # Set up mock to return None (user not found)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        body = {"email": "nonexistent@example.com", "password": "wrongpassword"}
        resp = client.post("/login", data=body, follow_redirects=False)
        assert resp.status_code == 303
        assert "error=bad_credentials" in resp.headers["location"]
    
    def test_login_empty_credentials_returns_303(self, client, clear_users, mock_db):
        """Test login with empty credentials returns redirect."""
        # Set up mock to return None (user not found)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        body = {"email": "   ", "password": "   "}  # Whitespace instead of empty
        resp = client.post("/login", data=body, follow_redirects=False)
        assert resp.status_code == 303
        assert "error=bad_credentials" in resp.headers["location"]
    
    def test_login_success_returns_redirect_and_sets_cookie(self, client, clear_users, mock_db):
        """Test successful login returns redirect and sets session cookie."""
        # Create test user with known password
        hashed_password = hash_password("password123")
        user = User(
            id=uuid.uuid4(),
            email="test@example.com",
            password_hash=hashed_password,
            is_active=True
        )
        
        # Set up mock to return our user
        mock_db.query.return_value.filter.return_value.first.return_value = user
        
        body = {"email": "test@example.com", "password": "password123"}
        resp = client.post("/login", data=body, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"].startswith("/dashboard")
        # Check for session cookie
        assert "cc_session" in resp.cookies
    
    def test_logout_success_returns_redirect_and_clears_cookie(self, client, mock_db):
        """Test successful logout returns redirect and clears cookie."""
        resp = client.post("/logout", follow_redirects=False)
        assert resp.status_code == 303
        assert "logged_out=1" in resp.headers["location"]
        # Check that session cookie is cleared
        assert resp.cookies.get("cc_session", "").strip() == ""
    
    def test_protected_route_without_auth_returns_redirect(self, client, mock_db):
        """Test accessing protected route without authentication returns redirect."""
        # Set up mock to return None (no user)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        resp = client.get("/roadmaps", follow_redirects=False)
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]
        assert "next=" in resp.headers["location"]


@pytest.fixture
def clear_users():
    """Clear all users before test."""
    # This would clear the database in a real implementation
    pass


@pytest.fixture
def mock_db():
    """Mock database session."""
    mock_db = Mock()
    mock_db.add = Mock()
    mock_db.commit = Mock()
    mock_db.flush = Mock()
    mock_db.query = Mock()
    mock_db.filter = Mock()
    mock_db.first = Mock()
    
    # Set up query chain
    mock_query = Mock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = None
    
    return mock_db


@pytest.fixture
def client(mock_db):
    """Create test client with mocked database."""
    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
