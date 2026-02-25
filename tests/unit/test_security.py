import pytest
import uuid
import datetime
from unittest.mock import Mock, patch

from app.auth.hashing import hash_password, verify_password
from app.auth.sessions import new_raw_token, hash_token, absolute_expiry
from app.jobs.tasks import _to_uuid, _ts


class TestSecurityUnit:
    """Unit tests for security-critical functions."""
    
    def test_password_hashing_strength(self):
        """Test password hashing provides adequate security."""
        password = "test_password_123"
        hashed = hash_password(password)
        
        # Test basic properties
        assert hashed != password
        assert len(hashed) >= 60  # bcrypt hashes are at least 60 chars
        assert hashed.startswith("$2b$")  # bcrypt identifier
        
        # Test verification works
        assert verify_password(password, hashed) is True
        assert verify_password("wrong", hashed) is False
        
        # Test same password produces different hashes (due to salt)
        hashed2 = hash_password(password)
        assert hashed != hashed2
        assert verify_password(password, hashed2) is True
    
    def test_password_length_limits(self):
        """Test password length limits are enforced."""
        # Test very long password (should be truncated to 72 bytes)
        long_password = "a" * 100
        hashed = hash_password(long_password)
        
        # Should still work (bcrypt truncates to 72 bytes)
        assert verify_password(long_password, hashed) is True
        
        # Test exactly 72 bytes
        exact_password = "a" * 72
        hashed_exact = hash_password(exact_password)
        assert verify_password(exact_password, hashed_exact) is True
    
    def test_session_token_security(self):
        """Test session token generation is secure."""
        token1 = new_raw_token()
        token2 = new_raw_token()
        
        # Tokens should be unique
        assert token1 != token2
        
        # Tokens should be URL-safe
        assert "+" not in token1 and "/" not in token1
        assert "=" not in token1  # No padding
        
        # Tokens should be sufficiently long
        assert len(token1) >= 32
        
        # Hash should be deterministic
        hash1 = hash_token(token1)
        hash2 = hash_token(token1)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length
    
    def test_session_expiry_calculation(self):
        """Test session expiry calculation is correct."""
        now = datetime.datetime.now(datetime.timezone.utc)
        expiry = absolute_expiry(now)
        
        # Should be 7 days from now
        expected = now + datetime.timedelta(days=7)
        assert expiry == expected
        
        # Test with None (should use current time)
        expiry_default = absolute_expiry(None)
        assert expiry_default > datetime.datetime.now(datetime.timezone.utc)
    
    def test_uuid_validation_security(self):
        """Test UUID validation prevents injection."""
        # Valid UUIDs
        valid_uuid = uuid.uuid4()
        assert _to_uuid(valid_uuid) == valid_uuid
        assert _to_uuid(str(valid_uuid)) == valid_uuid
        
        # None input
        assert _to_uuid(None) is None
        
        # Malicious inputs
        malicious = "'; DROP TABLE users; --"
        with pytest.raises(ValueError):
            _to_uuid(malicious)
        
        # Invalid UUID format
        with pytest.raises(ValueError):
            _to_uuid("not-a-uuid")
        
        # Empty string
        with pytest.raises(ValueError):
            _to_uuid("")
    
    def test_timestamp_formatting(self):
        """Test timestamp formatting is consistent."""
        ts = _ts()
        
        # Should be in expected format
        assert len(ts) == 19  # "YYYY-MM-DD HH:MM:SS"
        assert ts[4] == "-" and ts[7] == "-"  # Date separators
        assert ts[10] == " "  # Space between date and time
        assert ts[13] == ":" and ts[16] == ":"  # Time separators
        
        # Should be valid datetime
        datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    
    def test_edge_case_inputs(self):
        """Test edge cases in security functions."""
        # Empty password
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        
        # Unicode characters
        unicode_password = "🔐password🔐"
        hashed_unicode = hash_password(unicode_password)
        assert verify_password(unicode_password, hashed_unicode) is True
        
        # Special characters
        special_password = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
        hashed_special = hash_password(special_password)
        assert verify_password(special_password, hashed_special) is True
    
    def test_concurrent_session_safety(self):
        """Test concurrent session generation doesn't collide."""
        tokens = set()
        
        # Generate many tokens rapidly
        for _ in range(1000):
            token = new_raw_token()
            assert token not in tokens  # Should be unique
            tokens.add(token)
        
        # All should be unique
        assert len(tokens) == 1000
    
    def test_hash_collision_resistance(self):
        """Test hash function collision resistance."""
        token1 = new_raw_token()
        token2 = new_raw_token()
        
        # Different tokens should have different hashes
        hash1 = hash_token(token1)
        hash2 = hash_token(token2)
        assert hash1 != hash2
        
        # Even similar tokens should have different hashes
        similar_token = token1[:-1] + ("a" if token1[-1] != "a" else "b")
        hash_similar = hash_token(similar_token)
        assert hash1 != hash_similar
