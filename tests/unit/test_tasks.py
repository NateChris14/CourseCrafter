import pytest
import json
import uuid
import sys
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

# Mock langgraph imports before importing tasks
sys.modules['langgraph'] = Mock()
sys.modules['langgraph.graph'] = Mock()
sys.modules['langchain_core'] = Mock()
sys.modules['langchain_core.runnables'] = Mock()

from app.jobs.tasks import (
    enqueue_job,
    get_queue_status,
    clear_pending_queue,
    clear_processing_queue,
    cancel_job_by_run_id,
    generate_roadmap_outline_sync,
    _to_uuid,
    _ts
)
from app.db.models.generation_run import GenerationRun
from app.db.models.roadmap import Roadmap
from app.db.models.course import Course
from app.db.models.course_module import CourseModule


class TestTaskHelpers:
    """Test helper functions in tasks module."""
    
    def test_to_uuid_with_valid_string(self):
        """Test _to_uuid with valid UUID string."""
        uuid_str = "550e8400-e29b-41d4-a716-446655440000"
        result = _to_uuid(uuid_str)
        assert isinstance(result, uuid.UUID)
        assert str(result) == uuid_str
    
    def test_to_uuid_with_uuid_object(self):
        """Test _to_uuid with UUID object."""
        uuid_obj = uuid.uuid4()
        result = _to_uuid(uuid_obj)
        assert result == uuid_obj
    
    def test_to_uuid_with_none(self):
        """Test _to_uuid with None."""
        result = _to_uuid(None)
        assert result is None
    
    def test_to_uuid_with_invalid_string(self):
        """Test _to_uuid with invalid string."""
        with pytest.raises(ValueError):
            _to_uuid("invalid-uuid")
    
    def test_ts_format(self):
        """Test timestamp formatting."""
        result = _ts()
        # Should match format YYYY-MM-DD HH:MM:SS
        assert len(result) == 19
        assert result[4] == "-"
        assert result[7] == "-"
        assert result[10] == " "
        assert result[13] == ":"
        assert result[16] == ":"


class TestQueueOperations:
    """Test Redis queue operations."""
    
    def test_enqueue_job(self, mock_redis_client):
        """Test job enqueuing."""
        # Patch redis_client at module level before calling function
        with patch('app.jobs.tasks.redis_client', mock_redis_client):
            run_id = str(uuid.uuid4())
            task_id = enqueue_job(
                job_type="generate_roadmap_outline",
                run_id=run_id,
                course_id=None,
                overwrite=False
            )
        
        assert task_id is not None
        mock_redis_client.lpush.assert_called_once()
        
        # Verify the task data structure
        call_args = mock_redis_client.lpush.call_args[0]
        task_data = json.loads(call_args[1])
        
        assert task_data["task_id"] == task_id
        assert task_data["type"] == "generate_roadmap_outline"
        assert task_data["run_id"] == run_id
        assert task_data["course_id"] is None
        assert task_data["overwrite"] is False
        assert task_data["attempt"] == 0
        assert "timestamp" in task_data
    
    def test_get_queue_status_empty(self, mock_redis_client):
        """Test getting queue status when empty."""
        with patch('app.jobs.tasks.redis_client', mock_redis_client):
            mock_redis_client.lrange.return_value = []
            status = get_queue_status()
        
        assert status["pending_count"] == 0
        assert status["processing_count"] == 0
        assert status["pending"] == []
        assert status["processing"] == []
    
    def test_get_queue_status_with_tasks(self, mock_redis_client):
        """Test getting queue status with tasks."""
        pending_task = json.dumps({
            "task_id": "task-1",
            "type": "generate_roadmap_outline",
            "run_id": "run-1",
            "attempt": 0,
            "timestamp": "2024-01-01T00:00:00Z"
        })
        
        processing_task = json.dumps({
            "task_id": "task-2",
            "type": "generate_course_modules",
            "run_id": "run-2",
            "attempt": 1,
            "timestamp": "2024-01-01T01:00:00Z"
        })
        
        with patch('app.jobs.tasks.redis_client', mock_redis_client):
            # Mock the pipeline to return our test data
            mock_pipeline = Mock()
            mock_pipeline.lrange.side_effect = [[pending_task], [processing_task]]
            mock_pipeline.execute.return_value = [[pending_task], [processing_task]]
            mock_pipeline.__enter__ = Mock(return_value=mock_pipeline)
            mock_pipeline.__exit__ = Mock(return_value=None)
            mock_redis_client.pipeline.return_value = mock_pipeline
            
            status = get_queue_status()
        
        assert status["pending_count"] == 1
        assert status["processing_count"] == 1
        assert len(status["pending"]) == 1
        assert len(status["processing"]) == 1
        assert status["pending"][0]["task"]["task_id"] == "task-1"
        assert status["processing"][0]["task"]["task_id"] == "task-2"
    
    def test_clear_pending_queue(self, mock_redis_client):
        """Test clearing pending queue."""
        with patch('app.jobs.tasks.redis_client', mock_redis_client):
            mock_redis_client.lpop.side_effect = ["task1", "task2", None]
            count = clear_pending_queue()
        
        assert count == 2
        assert mock_redis_client.lpop.call_count == 3
    
    def test_clear_processing_queue(self, mock_redis_client, mock_db_session):
        """Test clearing processing queue."""
        # Create a test generation run
        run = GenerationRun(
            user_id=uuid.uuid4(),
            roadmap_id=uuid.uuid4(),
            status="processing",
            progress=50,
            message="Processing"
        )
        mock_db_session.add(run)
        mock_db_session.commit()
        
        processing_task = json.dumps({
            "task_id": "task-1",
            "type": "generate_roadmap_outline",
            "run_id": str(run.id),
            "attempt": 0,
            "timestamp": "2024-01-01T00:00:00Z"
        })
        
        with patch('app.jobs.tasks.redis_client', mock_redis_client), \
             patch('app.jobs.tasks.update_run') as mock_update:
            mock_redis_client.lrange.return_value = [processing_task]
            mock_redis_client.lrem.return_value = 1
            count = clear_processing_queue()
        
        assert count == 1
        mock_update.assert_called_once_with(
            str(run.id),
            status="failed",
            error="Cancelled by user (queue cleared)",
            finished=True
        )
    
    def test_cancel_job_by_run_id_pending(self, mock_redis_client, mock_db_session):
        """Test cancelling job from pending queue."""
        run = GenerationRun(
            user_id=uuid.uuid4(),
            roadmap_id=uuid.uuid4(),
            status="queued",
            progress=0,
            message="Queued"
        )
        mock_db_session.add(run)
        mock_db_session.commit()
        
        pending_task = json.dumps({
            "task_id": "task-1",
            "type": "generate_roadmap_outline",
            "run_id": str(run.id),
            "attempt": 0,
            "timestamp": "2024-01-01T00:00:00Z"
        })
        
        with patch('app.jobs.tasks.redis_client', mock_redis_client), \
             patch('app.jobs.tasks.update_run') as mock_update:
            mock_redis_client.lrange.return_value = [pending_task]
            mock_redis_client.lrem.return_value = 1
            result = cancel_job_by_run_id(str(run.id))
        
        assert result["ok"] is True
        assert result["removed_from"] == "pending"
        mock_update.assert_called_once_with(
            str(run.id),
            status="failed",
            error="Cancelled by user",
            finished=True
        )


class TestGenerationFunctions:
    """Test generation functions."""
    
    @patch('app.jobs.tasks.generate_roadmap_outline')
    @patch('app.jobs.tasks.SessionLocal')
    def test_generate_roadmap_outline_sync_success(self, mock_session_local, mock_generate_outline, test_roadmap):
        """Test successful roadmap outline generation."""
        # Setup mock session
        mock_session = Mock()
        mock_session_local.return_value = mock_session
        
        # Setup mock generation run
        mock_run = Mock()
        mock_run.id = test_roadmap.id
        mock_run.user_id = test_roadmap.user_id
        mock_run.roadmap = test_roadmap
        mock_run.status = "queued"
        mock_run.progress = 0
        mock_run.message = "Queued"
        mock_run.started_at = None
        mock_run.finished_at = None
        
        mock_session.query.return_value.options.return_value.filter.return_value.first.return_value = mock_run
        
        # Setup mock outline generation
        mock_outline = Mock()
        mock_outline.model_dump.return_value = {
            "field": "Computer Science",
            "level": "beginner",
            "duration_weeks": 8,
            "weeks": [
                {
                    "week": 1,
                    "title": "Introduction",
                    "outcomes": ["Learn basics"]
                }
            ]
        }
        mock_generate_outline.return_value = mock_outline
        
        # Mock course and module creation
        mock_course = Mock()
        mock_course.id = uuid.uuid4()
        mock_session.add = Mock()
        mock_session.flush = Mock()
        mock_session.bulk_insert_mappings = Mock()
        mock_session.commit = Mock()
        
        with patch('app.jobs.tasks.Course', return_value=mock_course):
            result = generate_roadmap_outline_sync(str(mock_run.id))
        
        assert result["ok"] is True
        assert "course_id" in result
        mock_generate_outline.assert_called_once_with(
            test_roadmap.field,
            test_roadmap.level,
            test_roadmap.weekly_hours,
            test_roadmap.duration_weeks
        )
        assert mock_session.commit.call_count >= 3  # Multiple commits during process
    
    @patch('app.jobs.tasks.SessionLocal')
    def test_generate_roadmap_outline_sync_run_not_found(self, mock_session_local):
        """Test roadmap generation when run not found."""
        mock_session = Mock()
        mock_session_local.return_value = mock_session
        mock_session.query.return_value.options.return_value.filter.return_value.first.return_value = None
        
        run_id = str(uuid.uuid4())
        result = generate_roadmap_outline_sync(run_id)
        
        assert result["ok"] is False
        assert result["error"] == "run not found"
    
    @patch('app.jobs.tasks.SessionLocal')
    def test_generate_roadmap_outline_sync_already_completed(self, mock_session_local):
        """Test roadmap generation when run already completed."""
        mock_session = Mock()
        mock_session_local.return_value = mock_session
        
        mock_run = Mock()
        mock_run.status = "succeeded"
        mock_session.query.return_value.options.return_value.filter.return_value.first.return_value = mock_run
        
        run_id = str(uuid.uuid4())
        result = generate_roadmap_outline_sync(run_id)
        
        assert result["ok"] is True
        assert result["skipped"] is True
        assert result["status"] == "succeeded"
    
    @patch('app.jobs.tasks.generate_roadmap_outline')
    @patch('app.jobs.tasks.SessionLocal')
    def test_generate_roadmap_outline_sync_roadmap_not_found(self, mock_session_local, mock_generate_outline):
        """Test roadmap generation when roadmap not found."""
        mock_session = Mock()
        mock_session_local.return_value = mock_session
        
        mock_run = Mock()
        mock_run.id = uuid.uuid4()
        mock_run.user_id = uuid.uuid4()
        mock_run.roadmap = None  # Roadmap not found
        mock_run.roadmap_id = uuid.uuid4()
        mock_run.status = "queued"
        mock_run.progress = 0
        mock_run.message = "Queued"
        mock_run.started_at = None
        mock_run.finished_at = None
        
        mock_session.query.return_value.options.return_value.filter.return_value.first.return_value = mock_run
        
        run_id = str(mock_run.id)
        result = generate_roadmap_outline_sync(run_id)
        
        assert result["ok"] is False
        assert result["error"] == "roadmap not found"
        assert mock_run.status == "failed"
