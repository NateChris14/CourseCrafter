import pytest
import json
import gzip
import datetime
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.deps import get_db
from app.db.models.user import User
from app.db.models.roadmap import Roadmap
from app.db.models.course import Course
from app.db.models.generation_run import GenerationRun
from app.auth.hashing import hash_password
import uuid


class TestGeneration:
    """Test generation routes."""
    
    def decompress_response(self, response):
        """Decompress gzipped response."""
        if response.headers.get("Content-Encoding") == "gzip":
            return json.loads(gzip.decompress(response.content).decode('utf-8'))
        return response.json()
    
    def test_start_roadmap_generation_success_returns_redirect_and_creates_run(self, client, clear_runs, mock_db):
        """Test successful roadmap generation returns redirect and creates run."""
        # Create test user and roadmap
        user = User(
            id=uuid.uuid4(),
            email="test@example.com",
            password_hash=hash_password("password123"),
            is_active=True
        )
        roadmap = Roadmap(
            id=uuid.uuid4(),
            user_id=user.id,
            title="Test Roadmap",
            field="Computer Science",
            level="beginner",
            duration_weeks=8,
            weekly_hours=10
        )
        
        # Reset mock and set up proper side effect
        mock_db.reset_mock()
        
        # Set up mock to return our roadmap for the specific query
        def mock_query_side_effect(*args, **kwargs):
            # For roadmap query
            if hasattr(mock_db.query.return_value.filter.return_value, 'id'):
                return roadmap
            return None
        
        mock_db.query.return_value.filter.return_value.first.side_effect = mock_query_side_effect
        
        # Mock Redis client
        with patch('app.jobs.tasks.redis_client') as mock_redis:
            mock_redis.lpush.return_value = "test-task-id"
            
            resp = client.post(f"/generation/roadmaps/{roadmap.id}/generate", follow_redirects=False)
            assert resp.status_code == 303
            assert "run=" in resp.headers["location"]
            # Verify run was created
            mock_db.add.assert_called_once()
            mock_db.flush.assert_called_once()
            mock_db.commit.assert_called_once()
            # Verify Redis was called
            mock_redis.lpush.assert_called_once()


@pytest.fixture
def clear_runs():
    """Clear all generation runs before test."""
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
    mock_db.all = Mock()
    
    # Set up query chain
    mock_query = Mock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = None
    mock_query.all.return_value = []
    
    return mock_db


@pytest.fixture
def client(mock_db):
    """Create test client with mocked database and authenticated user."""
    # Create test user
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        password_hash=hash_password("password123"),
        is_active=True
    )
    
    # Override get_current_user to return our test user
    from app.auth.deps import get_current_user
    def mock_get_current_user():
        return user
    
    app.dependency_overrides[get_current_user] = mock_get_current_user
    app.dependency_overrides[get_db] = lambda: mock_db
    
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
