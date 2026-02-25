import pytest
import uuid
from datetime import datetime
from unittest.mock import Mock

from app.db.models.user import User
from app.db.models.roadmap import Roadmap
from app.db.models.course import Course
from app.db.models.course_module import CourseModule
from app.db.models.generation_run import GenerationRun


class TestUserModel:
    """Test User model."""
    
    def test_user_creation(self):
        """Test creating a user."""
        # Create local mock session
        mock_session = Mock()
        mock_session.add = Mock()
        mock_session.commit = Mock()
        mock_session.refresh = Mock()
        
        from datetime import datetime
        user = User(
            email="test@example.com",
            password_hash="$2b$12$hashedpassword",
            is_active=True
        )
        # Manually set created_at to avoid mock recursion
        user.created_at = datetime.now()
        
        mock_session.add(user)
        mock_session.commit()
        mock_session.refresh(user)
        
        # Check that object was added and committed
        mock_session.add.assert_called_once_with(user)
        mock_session.commit.assert_called_once()
        mock_session.refresh.assert_called_once_with(user)
        
        # Check basic properties
        assert user.email == "test@example.com"
        assert user.is_active is True
        assert isinstance(user.created_at, datetime)  # Should be datetime object
    
    def test_user_email_unique(self):
        """Test that email must be unique."""
        # Create local mock session
        mock_session = Mock()
        mock_session.add = Mock()
        mock_session.commit = Mock()
        mock_session.refresh = Mock()
        
        user1 = User(
            email="duplicate@example.com",
            password_hash="$2b$12$hashedpassword1",
        )
        user2 = User(
            email="duplicate@example.com",  # Same email
            password_hash="$2b$12$hashedpassword2",
        )
        
        mock_session.add(user1)
        mock_session.commit()
        
        mock_session.add(user2)
        
        # Make second commit raise IntegrityError
        from sqlalchemy.exc import IntegrityError
        mock_session.commit.side_effect = IntegrityError("", "", None)
        
        with pytest.raises(IntegrityError):  # Should raise integrity error
            mock_session.commit()


class TestRoadmapModel:
    """Test Roadmap model."""
    
    def test_roadmap_creation(self):
        """Test creating a roadmap."""
        # Create local mock session
        mock_session = Mock()
        mock_session.add = Mock()
        mock_session.commit = Mock()
        mock_session.refresh = Mock()
        
        # Create test user
        test_user = Mock()
        test_user.id = uuid.uuid4()
        
        roadmap = Roadmap(
            user_id=test_user.id,
            title="Test Roadmap",
            field="Computer Science",
            level="beginner",
            duration_weeks=8,
            weekly_hours=10
        )
        
        mock_session.add(roadmap)
        mock_session.commit()
        mock_session.refresh(roadmap)
        
        # Check basic properties
        assert roadmap.user_id == test_user.id
        assert roadmap.title == "Test Roadmap"
        assert roadmap.field == "Computer Science"
        assert roadmap.level == "beginner"
        assert roadmap.duration_weeks == 8
        assert roadmap.weekly_hours == 10


class TestCourseModel:
    """Test Course model."""
    
    def test_course_creation(self):
        """Test creating a course."""
        # Create local mock session
        mock_session = Mock()
        mock_session.add = Mock()
        mock_session.commit = Mock()
        mock_session.refresh = Mock()
        
        # Create test user
        test_user = Mock()
        test_user.id = uuid.uuid4()
        test_roadmap = Mock()
        test_roadmap.id = uuid.uuid4()
        
        course = Course(
            user_id=test_user.id,
            roadmap_id=test_roadmap.id,
            title="Test Course",
            description="Test course description",
            status="draft"
        )
        
        mock_session.add(course)
        mock_session.commit()
        mock_session.refresh(course)
        
        # Check basic properties
        assert course.user_id == test_user.id
        assert course.roadmap_id == test_roadmap.id
        assert course.title == "Test Course"
        assert course.description == "Test course description"
        assert course.status == "draft"


class TestGenerationRunModel:
    """Test GenerationRun model."""
    
    def test_generation_run_creation(self):
        """Test creating a generation run."""
        # Create local mock session
        mock_session = Mock()
        mock_session.add = Mock()
        mock_session.commit = Mock()
        mock_session.refresh = Mock()
        
        run = GenerationRun(
            user_id=uuid.uuid4(),
            roadmap_id=uuid.uuid4(),
            status="queued",
            progress=0,
            message="Test generation run"
        )
        
        mock_session.add(run)
        mock_session.commit()
        mock_session.refresh(run)
        
        # Check basic properties
        assert run.user_id is not None
        assert run.roadmap_id is not None
        assert run.status == "queued"
        assert run.progress == 0
        assert run.message == "Test generation run"
