"""Unit tests for agent validation functions."""
import pytest
from pydantic import ValidationError

from app.agents.workflow import _extract_first_json_object, _validate_outline, generate_roadmap_outline
from app.agents.schemas import RoadmapOutline
from app.agents.module_writer import validate_module_markdown, write_module_markdown
from app.exceptions.custom_exception import DocumentPortalException
from unittest.mock import Mock, patch


class TestWorkflowValidation:
    """Test workflow.py validation functions."""
    
    def test_extract_first_json_object_valid_json(self):
        """Test extracting valid JSON object from text."""
        text = '{"test": "value"} some other text'
        result = _extract_first_json_object(text)
        assert result == '{"test": "value"}'
    
    def test_extract_first_json_object_nested_braces(self):
        """Test extracting JSON with nested braces."""
        text = '{"outer": {"inner": "value", "nested": {"deep": "data"}}} more text'
        result = _extract_first_json_object(text)
        assert result == '{"outer": {"inner": "value", "nested": {"deep": "data"}}}'
    
    def test_extract_first_json_object_no_braces(self):
        """Test returns None when no braces found."""
        text = 'no json here'
        result = _extract_first_json_object(text)
        assert result is None
    
    def test_extract_first_json_object_incomplete_braces(self):
        """Test returns None when braces are incomplete."""
        text = '{"incomplete": "value"'
        result = _extract_first_json_object(text)
        assert result is None
    
    def test_validate_outline_correct_structure(self):
        """Test validation passes for correct outline."""
        outline = RoadmapOutline(
            weeks=[
                {"week": 1, "title": "Introduction", "outcomes": ["Learn basics", "Setup environment"]},
                {"week": 2, "title": "Advanced Topics", "outcomes": ["Master concepts", "Build project"]},
                {"week": 3, "title": "Practice", "outcomes": ["Apply skills", "Build portfolio"]},
                {"week": 4, "title": "Review", "outcomes": ["Review concepts", "Final project"]}
            ]
        )
        # Should not raise exception
        _validate_outline(outline, 4)
    
    def test_validate_outline_wrong_week_count(self):
        """Test validation fails with wrong week count."""
        outline = RoadmapOutline(
            weeks=[
                {"week": 1, "title": "Introduction", "outcomes": ["Learn basics", "Setup env"]},
                {"week": 2, "title": "Advanced", "outcomes": ["Learn advanced", "Practice"]},
                {"week": 3, "title": "Topics", "outcomes": ["More topics", "Apply"]},
                {"week": 4, "title": "Final", "outcomes": ["Review", "Project"]}
            ]
        )
        with pytest.raises(ValueError, match="Expected 2 weeks, got 4"):
            _validate_outline(outline, 2)
    
    def test_validate_outline_wrong_week_numbers(self):
        """Test validation fails with wrong week numbers."""
        outline = RoadmapOutline(
            weeks=[
                {"week": 1, "title": "Introduction", "outcomes": ["Learn basics", "Setup"]},
                {"week": 3, "title": "Skip", "outcomes": ["Learn advanced", "Practice"]},  # Should be week 2
                {"week": 2, "title": "Missing", "outcomes": ["More stuff", "Apply"]},
                {"week": 4, "title": "Final", "outcomes": ["Review", "Project"]}
            ]
        )
        with pytest.raises(ValueError, match="Week numbers must be exactly 1..4"):
            _validate_outline(outline, 4)
    
    def test_validate_outline_empty_title(self):
        """Test validation fails with empty title."""
        # Create a valid outline first, then modify it for testing
        outline = RoadmapOutline(
            weeks=[
                {"week": 1, "title": "Introduction", "outcomes": ["Learn basics", "Setup"]},
                {"week": 2, "title": "Advanced", "outcomes": ["Learn advanced", "Practice"]},
                {"week": 3, "title": "Topics", "outcomes": ["More topics", "Apply"]},
                {"week": 4, "title": "Final", "outcomes": ["Review", "Project"]}
            ]
        )
        # Manually set empty title to test validation
        outline.weeks[0].title = ""
        with pytest.raises(ValueError, match="Week 1 title is empty"):
            _validate_outline(outline, 4)
    
    def test_validate_outline_too_few_outcomes(self):
        """Test validation fails with too few outcomes."""
        # Create a valid outline first, then modify it for testing
        outline = RoadmapOutline(
            weeks=[
                {"week": 1, "title": "Introduction", "outcomes": ["Learn basics", "Setup"]},
                {"week": 2, "title": "Advanced", "outcomes": ["Learn advanced", "Practice"]},
                {"week": 3, "title": "Topics", "outcomes": ["More topics", "Apply"]},
                {"week": 4, "title": "Final", "outcomes": ["Review", "Project"]}
            ]
        )
        # Manually set only 1 outcome to test validation
        outline.weeks[0].outcomes = ["Learn basics"]  # Only 1 outcome
        with pytest.raises(ValueError, match="Week 1 must have 2-6 outcomes"):
            _validate_outline(outline, 4)
    
    def test_validate_outline_too_many_outcomes(self):
        """Test validation fails with too many outcomes."""
        outline = RoadmapOutline(
            weeks=[
                {"week": 1, "title": "Introduction", "outcomes": ["1", "2", "3", "4", "5", "6", "7"]},  # 7 outcomes
                {"week": 2, "title": "Advanced", "outcomes": ["Learn advanced", "Practice"]},
                {"week": 3, "title": "Topics", "outcomes": ["More topics", "Apply"]},
                {"week": 4, "title": "Final", "outcomes": ["Review", "Project"]}
            ]
        )
        with pytest.raises(ValueError, match="Week 1 must have 2-6 outcomes"):
            _validate_outline(outline, 4)
    
    def test_validate_outline_empty_outcome(self):
        """Test validation fails with empty outcome."""
        outline = RoadmapOutline(
            weeks=[
                {"week": 1, "title": "Introduction", "outcomes": ["Learn basics", ""]},  # Empty outcome
                {"week": 2, "title": "Advanced", "outcomes": ["Learn advanced", "Practice"]},
                {"week": 3, "title": "Topics", "outcomes": ["More topics", "Apply"]},
                {"week": 4, "title": "Final", "outcomes": ["Review", "Project"]}
            ]
        )
        with pytest.raises(ValueError, match="Week 1 has empty outcome"):
            _validate_outline(outline, 4)


class TestModuleWriterValidation:
    """Test module_writer.py validation functions."""
    
    def test_validate_module_markdown_correct_structure(self):
        """Test validation passes for correct markdown structure."""
        markdown = """## Overview
This is an overview.

## Key concepts
Concept 1, Concept 2

## Worked example
Here's a worked example.

## Practice exercises
1. Exercise one
2. Exercise two  
3. Exercise three

## Common mistakes
Common mistake 1, Common mistake 2

## Suggested resources
Resource 1, Resource 2

## Media suggestions
- Image: diagram showing flow - search keywords: flow diagram
- Video: tutorial - search keywords: tutorial video
"""
        # Should not raise exception
        validate_module_markdown(markdown)
    
    def test_validate_module_markdown_missing_heading(self):
        """Test validation fails when heading is missing."""
        markdown = """## Overview
This is an overview.

## Key concepts
Concept 1, Concept 2

## Worked example
Here's a worked example.

## Practice exercises
1. Exercise one
2. Exercise two  
3. Exercise three

## Common mistakes
Common mistake 1, Common mistake 2

## Suggested resources
Resource 1, Resource 2
# Missing Media suggestions heading
"""
        with pytest.raises(ValueError, match="Missing.*Media suggestions"):
            validate_module_markdown(markdown)
    
    def test_validate_module_markdown_wrong_practice_count(self):
        """Test validation fails with wrong number of practice exercises."""
        markdown = """## Overview
This is an overview.

## Key concepts
Concept 1, Concept 2

## Worked example
Here's a worked example.

## Practice exercises
1. Exercise one
2. Exercise two
# Only 2 exercises, should be 3

## Common mistakes
Common mistake 1, Common mistake 2

## Suggested resources
Resource 1, Resource 2

## Media suggestions
- Image: diagram - search keywords: diagram
"""
        with pytest.raises(ValueError, match="Practice exercises must have exactly 3 numbered items"):
            validate_module_markdown(markdown)
    
    def test_validate_module_markdown_extra_headings(self):
        """Test validation fails with extra headings."""
        markdown = """## Overview
This is an overview.

## Key concepts
Concept 1, Concept 2

## Extra heading
This should not be here.

## Worked example
Here's a worked example.

## Practice exercises
1. Exercise one
2. Exercise two  
3. Exercise three

## Common mistakes
Common mistake 1, Common mistake 2

## Suggested resources
Resource 1, Resource 2

## Media suggestions
- Image: diagram - search keywords: diagram
"""
        with pytest.raises(ValueError, match="Extra.*extra heading"):
            validate_module_markdown(markdown)
    
    def test_validate_module_markdown_case_insensitive(self):
        """Test validation works with different heading cases."""
        markdown = """## overview
This is an overview.

## KEY CONCEPTS
Concept 1, Concept 2

## worked example
Here's a worked example.

## practice exercises
1. Exercise one
2. Exercise two  
3. Exercise three

## common mistakes
Common mistake 1, Common mistake 2

## suggested resources
Resource 1, Resource 2

## media suggestions
- Image: diagram - search keywords: diagram
"""
        # Should not raise exception
        validate_module_markdown(markdown)


class TestAgentIntegration:
    """Test agent integration with mocked LLM."""
    
    @patch('app.agents.workflow.get_llm_client')
    def test_generate_roadmap_outline_success(self, mock_get_client):
        """Test successful roadmap generation."""
        mock_llm = Mock()
        mock_llm.generate_text.return_value = '{"weeks": [{"week": 1, "title": "Intro", "outcomes": ["Learn basics", "Setup env"]}, {"week": 2, "title": "Advanced", "outcomes": ["Master concepts", "Build project"]}, {"week": 3, "title": "Practice", "outcomes": ["Apply skills", "Build portfolio"]}, {"week": 4, "title": "Review", "outcomes": ["Review concepts", "Final project"]}]}'
        mock_get_client.return_value = mock_llm
        
        result = generate_roadmap_outline("Python", "beginner", 5, 4)
        assert len(result.weeks) == 4
        assert result.weeks[0].week == 1
        assert result.weeks[0].title == "Intro"
        assert "Learn basics" in result.weeks[0].outcomes
    
    @patch('app.agents.workflow.get_llm_client')
    def test_generate_roadmap_outline_with_repair(self, mock_get_client):
        """Test roadmap generation with repair cycle."""
        mock_llm = Mock()
        # First call returns invalid JSON, second call returns valid
        mock_llm.generate_text.side_effect = [
            'invalid json {"weeks": [{"week": 1, "title": "Intro", "outcomes": ["Learn basics", "Setup"]}]}',
            '{"weeks": [{"week": 1, "title": "Intro", "outcomes": ["Learn basics", "Setup"]}, {"week": 2, "title": "Advanced", "outcomes": ["Master concepts", "Practice"]}, {"week": 3, "title": "Topics", "outcomes": ["More topics", "Apply"]}, {"week": 4, "title": "Final", "outcomes": ["Review", "Project"]}]}'
        ]
        mock_get_client.return_value = mock_llm
        
        result = generate_roadmap_outline("Python", "beginner", 5, 4)
        assert len(result.weeks) == 4
        assert result.weeks[0].title == "Intro"
    
    @patch('app.agents.workflow.get_llm_client')
    def test_generate_roadmap_outline_failure_after_retries(self, mock_get_client):
        """Test roadmap generation fails after max retries."""
        mock_llm = Mock()
        mock_llm.generate_text.return_value = 'always invalid json'
        mock_get_client.return_value = mock_llm
        
        with pytest.raises(RuntimeError, match="Planner output did not validate after retries"):
            generate_roadmap_outline("Python", "beginner", 5, 4)
    
    @patch('app.agents.module_writer.get_llm_client')
    def test_write_module_markdown_success(self, mock_get_client):
        """Test successful module markdown generation."""
        mock_llm = Mock()
        mock_llm.generate_text.return_value = """## Overview
Overview content.

## Key concepts
Concept content.

## Worked example
Example content.

## Practice exercises
1. Exercise one
2. Exercise two
3. Exercise three

## Common mistakes
Mistakes content.

## Suggested resources
Resources content.

## Media suggestions
- Image: diagram - search keywords: diagram
"""
        mock_get_client.return_value = mock_llm
        
        result = write_module_markdown("Python", "beginner", 1, "Intro", ["Learn basics"])
        assert "## Overview" in result
        assert "Exercise one" in result
    
    @patch('app.agents.module_writer.get_llm_client')
    def test_write_module_markdown_with_repair(self, mock_get_client):
        """Test module markdown generation with repair."""
        mock_llm = Mock()
        # First call invalid (missing heading), second call valid
        mock_llm.generate_text.side_effect = [
            """## Overview
Overview content.

## Key concepts
Concept content.

## Worked example
Example content.

## Practice exercises
1. Exercise one
2. Exercise two
3. Exercise three

## Common mistakes
Mistakes content.

## Suggested resources
Resources content.
# Missing Media suggestions
""",
            """## Overview
Overview content.

## Key concepts
Concept content.

## Worked example
Example content.

## Practice exercises
1. Exercise one
2. Exercise two
3. Exercise three

## Common mistakes
Mistakes content.

## Suggested resources
Resources content.

## Media suggestions
- Image: diagram - search keywords: diagram
"""
        ]
        mock_get_client.return_value = mock_llm
        
        result = write_module_markdown("Python", "beginner", 1, "Intro", ["Learn basics"])
        assert "## Media suggestions" in result
    
    @patch('app.agents.module_writer.get_llm_client')
    def test_write_module_markdown_failure_after_repair(self, mock_get_client):
        """Test module markdown generation fails after repair attempt."""
        mock_llm = Mock()
        # Both calls return invalid markdown
        mock_llm.generate_text.return_value = "Invalid markdown without proper headings"
        mock_get_client.return_value = mock_llm
        
        with pytest.raises(DocumentPortalException, match="Module markdown validation failed after repair"):
            write_module_markdown("Python", "beginner", 1, "Intro", ["Learn basics"])
