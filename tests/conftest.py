import os
import io
import types
import json
import shutil
import pathlib
import sys
import pytest
import uuid
from unittest.mock import Mock, patch, MagicMock
from typing import Generator, Dict, Any

# Mock langgraph imports BEFORE any other imports
sys.modules['langgraph'] = Mock()
sys.modules['langgraph.graph'] = Mock()
sys.modules['langchain_core'] = Mock()
sys.modules['langchain_core.runnables'] = Mock()

# Set up test environment
os.environ.setdefault("PYTHONPATH", str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")  # Use test DB
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/coursegenerate_test")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("LANGGRAPH_POSTGRES_DSN", "postgresql://test:test@localhost:5432/coursegenerate_test")

from fastapi.testclient import TestClient

# Ensure repository root is importable
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.main
from app.deps import get_db
from app.db.base import Base
from app.db.models.user import User
from app.auth.deps import get_current_user
from app.settings import settings


@pytest.fixture
def mock_db_session():
    """Create mocked database session."""
    mock_session = Mock()
    mock_session.add = Mock()
    mock_session.commit = Mock()
    mock_session.flush = Mock()
    mock_session.refresh = Mock()
    mock_session.close = Mock()
    mock_session.query = Mock()
    mock_session.bulk_insert_mappings = Mock()
    
    # Mock query chain
    mock_query = Mock()
    mock_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.filter.return_value.options.return_value = mock_query
    mock_query.first.return_value = None
    mock_query.all.return_value = []
    
    return mock_session


@pytest.fixture
def mock_redis_client():
    """Create mocked Redis client."""
    mock_redis = Mock()
    mock_redis.lpush.return_value = "test-task-id"
    mock_redis.brpoplpush.return_value = None
    mock_redis.lrange.return_value = []
    mock_redis.lrem.return_value = 1
    mock_redis.lpop.return_value = None
    mock_redis.flushdb.return_value = True
    
    # Mock pipeline context manager properly
    mock_pipeline = Mock()
    mock_pipeline.lrange.return_value = []
    mock_pipeline.execute.return_value = [[], []]
    
    # Create proper context manager mock
    mock_pipeline.__enter__ = Mock(return_value=mock_pipeline)
    mock_pipeline.__exit__ = Mock(return_value=None)
    mock_redis.pipeline.return_value = mock_pipeline
    
    return mock_redis


@pytest.fixture
def client(mock_db_session):
    """Create test client with mocked database."""
    def override_get_db():
        yield mock_db_session
    
    app.main.app.dependency_overrides[get_db] = override_get_db
    with TestClient(app.main.app) as test_client:
        yield test_client
    app.main.app.dependency_overrides.clear()


@pytest.fixture
def test_user():
    """Create test user object."""
    return User(
        id=uuid.uuid4(),
        email="test@example.com",
        password_hash="$2b$12$test.hashed.password",
        is_active=True
    )


@pytest.fixture
def authenticated_client(client, test_user):
    """Create authenticated test client."""
    def override_get_current_user():
        return test_user
    
    app.main.app.dependency_overrides[get_current_user] = override_get_current_user
    yield client
    app.main.app.dependency_overrides.clear()


@pytest.fixture
def test_roadmap(test_user):
    """Create test roadmap object."""
    from app.db.models.roadmap import Roadmap
    
    return Roadmap(
        id=uuid.uuid4(),
        user_id=test_user.id,
        title="Test Roadmap",
        field="Computer Science",
        level="beginner",
        duration_weeks=8,
        weekly_hours=10
    )


@pytest.fixture
def test_course(test_user, test_roadmap):
    """Create test course object."""
    from app.db.models.course import Course
    
    return Course(
        id=uuid.uuid4(),
        user_id=test_user.id,
        roadmap_id=test_roadmap.id,
        title="Test Course",
        description="Test course for unit testing",
        status="draft"
    )


@pytest.fixture
def test_generation_run(test_user, test_roadmap):
    """Create test generation run object."""
    from app.db.models.generation_run import GenerationRun
    
    return GenerationRun(
        id=uuid.uuid4(),
        user_id=test_user.id,
        roadmap_id=test_roadmap.id,
        status="queued",
        progress=0,
        message="Test generation run"
    )


class _StubLLM:
    """Stub LLM for testing."""
    def __init__(self, response="stubbed response"):
        self.response = response
    
    def invoke(self, input_data):
        return self.response
    
    def __call__(self, *args, **kwargs):
        return self.response


class _StubEmbeddings:
    """Stub embeddings for testing."""
    def embed_query(self, text: str):
        return [0.0, 0.1, 0.2] * 128  # Return 384-dim vector
    
    def embed_documents(self, texts):
        return [[0.0, 0.1, 0.2] * 128 for _ in texts]
    
    def __call__(self, text: str):
        return [0.0, 0.1, 0.2] * 128


class _StubRoadmapOutline:
    """Stub roadmap outline for testing."""
    def model_dump(self):
        return {
            "field": "Computer Science",
            "level": "beginner",
            "duration_weeks": 8,
            "weeks": [
                {
                    "week": 1,
                    "title": "Introduction to Programming",
                    "outcomes": ["Basic syntax", "Variables", "Control flow"]
                },
                {
                    "week": 2,
                    "title": "Data Structures",
                    "outcomes": ["Arrays", "Lists", "Dictionaries"]
                }
            ]
        }


@pytest.fixture
def stub_llm(monkeypatch):
    """Patch LLM calls with stub."""
    # Patch OpenAI client
    mock_openai = Mock()
    mock_openai.chat.completions.create.return_value = Mock(
        choices=[Mock(message=Mock(content="stubbed roadmap outline"))]
    )
    
    with patch('openai.OpenAI', return_value=mock_openai):
        yield mock_openai


@pytest.fixture
def stub_embeddings(monkeypatch):
    """Patch embedding calls with stub."""
    with patch('app.agents.workflow.get_embeddings', return_value=_StubEmbeddings()):
        yield _StubEmbeddings()


@pytest.fixture
def stub_roadmap_generator(monkeypatch):
    """Patch roadmap generation with stub."""
    def mock_generate_roadmap_outline(field, level, weekly_hours, duration_weeks):
        return _StubRoadmapOutline()
    
    monkeypatch.setattr(
        "app.agents.workflow.generate_roadmap_outline",
        mock_generate_roadmap_outline
    )
    return mock_generate_roadmap_outline


@pytest.fixture
def stub_langgraph_builder(monkeypatch):
    """Patch LangGraph course generation."""
    mock_builder = Mock()
    mock_graph = Mock()
    mock_builder.compile.return_value = mock_graph
    
    def mock_build_course_generation_graph_builder():
        return mock_builder
    
    monkeypatch.setattr(
        "app.jobs.tasks.build_course_generation_graph_builder",
        mock_build_course_generation_graph_builder
    )
    return mock_builder


@pytest.fixture
def tmp_dirs(tmp_path: pathlib.Path):
    """Create temporary directories for file operations."""
    data_dir = tmp_path / "data"
    uploads_dir = tmp_path / "uploads"
    data_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    
    cwd = pathlib.Path().cwd()
    try:
        os.chdir(tmp_path)
        yield {"data": data_dir, "uploads": uploads_dir}
    finally:
        os.chdir(cwd)


@pytest.fixture
def mock_redis(monkeypatch):
    """Mock Redis client for testing."""
    mock_redis_client = Mock()
    mock_redis_client.lpush.return_value = "task_id"
    mock_redis_client.brpoplpush.return_value = json.dumps({
        "task_id": "test-task-id",
        "type": "generate_roadmap_outline",
        "run_id": "test-run-id",
        "attempt": 0,
        "timestamp": "2024-01-01T00:00:00Z"
    })
    mock_redis_client.lrange.return_value = []
    mock_redis_client.lrem.return_value = 1
    mock_redis_client.lpop.return_value = None
    mock_redis_client.flushdb.return_value = True
    
    monkeypatch.setattr("app.jobs.tasks.redis_client", mock_redis_client)
    return mock_redis_client
