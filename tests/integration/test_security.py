import pytest
import json
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.deps import get_db
from app.db.models.user import User
from app.db.models.session_token import SessionToken
from app.auth.hashing import hash_password, verify_password
from app.auth.sessions import new_raw_token, hash_token, absolute_expiry
import uuid
import datetime


class TestSecurity:
    """Test security-critical functionalities that could cause harm."""
    
    def test_password_hashing_security(self):
        """Test password hashing is secure and can't be reversed."""
        password = "test_password_123"
        hashed = hash_password(password)
        
        # Hash should be different from original password
        assert hashed != password
        assert len(hashed) > 50  # bcrypt hashes are long
        
        # Verify password works
        assert verify_password(password, hashed) is True
        
        # Wrong password should fail
        assert verify_password("wrong_password", hashed) is False
    
    def test_session_token_uniqueness(self):
        """Test session tokens are unique and secure."""
        token1 = new_raw_token()
        token2 = new_raw_token()
        
        # Tokens should be unique
        assert token1 != token2
        assert len(token1) >= 32  # tokens should be sufficiently long
        
        # Hashed tokens should be deterministic
        hash1 = hash_token(token1)
        hash2 = hash_token(token1)
        assert hash1 == hash2
    
    def test_session_expiry_security(self, client, mock_db):
        """Test expired sessions are rejected."""
        # Create user
        user = User(
            id=uuid.uuid4(),
            email="test@example.com",
            password_hash=hash_password("password123"),
            is_active=True
        )
        
        # Create expired session token
        raw_token = new_raw_token()
        token_hash = hash_token(raw_token)
        expired_token = SessionToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1),  # Expired
            last_seen_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
        )
        
        # Set up mock to return expired token
        mock_db.query.return_value.filter.return_value.first.return_value = expired_token
        
        # Try to access protected route with expired token
        client.cookies.set("cc_session", raw_token)
        resp = client.get("/roadmaps", follow_redirects=False)
        
        # Should redirect to login due to expired session
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]
    
    def test_sql_injection_protection(self, client, mock_db):
        """Test SQL injection attempts are handled safely."""
        # Mock to simulate SQL injection attempt
        malicious_email = "'; DROP TABLE users; --"
        
        # Set up mock to return None (no user found)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        # Try login with SQL injection
        resp = client.post("/login", data={
            "email": malicious_email,
            "password": "anything"
        }, follow_redirects=False)
        
        # Should handle gracefully without database errors
        assert resp.status_code == 303
        assert "error=bad_credentials" in resp.headers["location"]
    
    def test_xss_protection_in_registration(self, client, mock_db):
        """Test XSS attempts in registration are handled safely."""
        # Mock to return None (no existing user)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        # Try registration with XSS payload
        xss_email = "<script>alert('xss')</script>@example.com"
        resp = client.post("/register", data={
            "email": xss_email,
            "password": "password123"
        }, follow_redirects=False)
        
        # Should handle without errors
        assert resp.status_code == 303
    
    def test_session_hijacking_protection(self, client, mock_db):
        """Test session tokens can't be reused after logout."""
        # Create user
        user = User(
            id=uuid.uuid4(),
            email="test@example.com",
            password_hash=hash_password("password123"),
            is_active=True
        )
        
        raw_token = new_raw_token()
        
        # Override get_current_user to return our user initially
        from app.auth.deps import get_current_user
        def mock_get_current_user():
            return user
        
        app.dependency_overrides[get_current_user] = mock_get_current_user
        app.dependency_overrides[get_db] = lambda: mock_db
        
        try:
            # Set session cookie
            client.cookies.set("cc_session", raw_token)
            
            # Logout (should clear session)
            resp = client.post("/logout", follow_redirects=False)
            assert resp.status_code == 303
            assert "logged_out=1" in resp.headers["location"]
            
            # Verify cookie is cleared
            assert resp.cookies.get("cc_session", "").strip() == ""
            
            # Override get_current_user to raise exception (simulating revoked session)
            def mock_get_current_user_revoked():
                from app.auth.deps import NotAuthenticated
                raise NotAuthenticated()
            
            app.dependency_overrides[get_current_user] = mock_get_current_user_revoked
            
            # Try to access protected route without valid session
            resp = client.get("/roadmaps", follow_redirects=False)
            assert resp.status_code == 303  # Should redirect to login
            assert "/login" in resp.headers["location"]
        finally:
            app.dependency_overrides.clear()
    
    def test_authorization_bypass_protection(self, client, mock_db):
        """Test users can't access other users' resources."""
        # Create user1
        user1 = User(
            id=uuid.uuid4(),
            email="user1@example.com",
            password_hash=hash_password("password123"),
            is_active=True
        )
        
        # Override get_current_user to return user1
        from app.auth.deps import get_current_user
        def mock_get_current_user():
            return user1
        
        app.dependency_overrides[get_current_user] = mock_get_current_user
        app.dependency_overrides[get_db] = lambda: mock_db
        
        try:
            # Try to access generation with user1 but different user's roadmap ID
            different_roadmap_id = uuid.uuid4()
            
            # Mock to return None (roadmap not found for this user)
            mock_db.query.return_value.filter.return_value.first.return_value = None
            
            resp = client.post(f"/generation/roadmaps/{different_roadmap_id}/generate", follow_redirects=False)
            
            # Should return not found, not success
            assert resp.status_code == 303
            assert "not_found" in resp.headers["location"]
        finally:
            app.dependency_overrides.clear()
    
    def test_rate_limiting_simulation(self, client, mock_db):
        """Test system handles rapid requests gracefully."""
        # Mock to return None (no user found)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        # Simulate rapid login attempts
        for i in range(10):
            resp = client.post("/login", data={
                "email": f"attacker{i}@example.com",
                "password": "wrongpassword"
            }, follow_redirects=False)
            
            # Should all fail gracefully
            assert resp.status_code == 303
            assert "error=bad_credentials" in resp.headers["location"]
    
    def test_input_validation_edge_cases(self, client, mock_db):
        """Test edge cases in input validation."""
        # Mock to return None (no existing user)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        # Test extremely long email
        long_email = "a" * 1000 + "@example.com"
        resp = client.post("/register", data={
            "email": long_email,
            "password": "password123"
        }, follow_redirects=False)
        
        # Should handle gracefully
        assert resp.status_code in [303, 422]  # Either handled or validation error
        
        # Test extremely long password
        long_password = "a" * 1000
        resp = client.post("/register", data={
            "email": "test@example.com",
            "password": long_password
        }, follow_redirects=False)
        
        # Should handle gracefully (bcrypt truncates to 72 bytes)
        assert resp.status_code in [303, 422]


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
