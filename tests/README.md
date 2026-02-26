# CourseGenerate Test Suite

This directory contains the comprehensive test suite for the CourseGenerate application with 66 tests (100% passing) covering all critical functionality.

## Test Coverage Summary

- Total Tests: 66 tests
- Pass Rate: 100%
- Unit Tests: 51 tests (business logic, utilities, security, data models, agent validation)
- Integration Tests: 15 tests (API endpoints, authentication, generation workflow)

## Test Categories

### Agent Validation Tests (22 tests)
- Agent Validation (22 tests) - workflow and module writer validation functions

### Security Tests (9 tests)
- Password hashing security - bcrypt strength, uniqueness, length limits
- Session token security - uniqueness, randomness, collision resistance
- Session expiry security - expired sessions rejected properly
- SQL injection protection - malicious inputs handled safely
- XSS protection - script tags in registration handled safely
- Session hijacking protection - tokens can't be reused after logout
- Authorization bypass protection - users can't access others' resources
- Rate limiting simulation - rapid requests handled gracefully
- Input validation edge cases - extreme inputs handled safely

### Unit Tests (20 tests)
- Task Helpers (5 tests) - UUID conversion, timestamp formatting
- Queue Operations (6 tests) - job enqueueing, status, clearing, cancellation
- Generation Functions (4 tests) - roadmap generation workflow orchestration
- Model Tests (5 tests) - User, Roadmap, Course, GenerationRun models

### Integration Tests (15 tests)
- Authentication Routes (5 tests) - login, registration, logout, protected routes
- Generation Routes (1 test) - roadmap generation workflow with Redis mocking
- Security Tests (9 tests) - authentication, authorization, vulnerability prevention

### LLM Integration (Mocked)
LLM functionality is tested via mocking (best practice for external dependencies):
- Task orchestration and workflow management
- Error handling for LLM-related operations
- Application logic around LLM calls
- Agent evaluation and quality assessment

## Structure

```
tests/
├── conftest.py              # Pytest configuration and shared fixtures
├── unit/                    # Unit tests
│   ├── test_models_simple.py     # Database model tests
│   ├── test_tasks.py           # Background task tests
│   ├── test_security.py        # Security-critical function tests
│   ├── test_agents.py          # AI agent validation tests
│   └── __init__.py
├── integration/             # Integration tests
│   ├── test_auth.py            # Authentication routes tests
│   ├── test_generation.py     # Generation routes tests
│   ├── test_security.py       # Security integration tests
│   └── __init__.py
└── README.md               # This file
```

## Running Tests

### Install Test Dependencies

```bash
uv sync
```

### Run All Tests

```bash
uv run pytest
```

### Run Specific Test Categories

```bash
# Run only unit tests
uv run pytest tests/unit/

# Run only integration tests
uv run pytest tests/integration/

# Run agent evaluation tests only
uv run pytest tests/unit/test_agents.py tests/unit/test_evaluation.py

# Run security tests only
uv run pytest tests/unit/test_security.py tests/integration/test_security.py

# Run specific test file
uv run pytest tests/unit/test_tasks.py
```

### Run with Coverage

```bash
uv run pytest --cov=app --cov-report=html
```

### Run with Verbose Output

```bash
uv run pytest -v
```

## Test Configuration

### Environment Variables

Tests use the following environment variables (configured in `conftest.py`):

- `REDIS_URL`: Redis connection for tests (uses DB 1)
- `DATABASE_URL`: PostgreSQL database for tests
- `GROQ_API_KEY`: Dummy API key for tests
- `OLLAMA_BASE_URL`: Ollama server URL for tests
- `SESSION_SECRET`: Test session secret

### Key Fixtures

The test suite provides several critical fixtures:

- `mock_db`: Mocked database session for all database operations
- `client`: FastAPI test client with dependency overrides
- `clear_users`, `clear_runs`: Cleanup fixtures for test isolation
- `stub_llm`: Mocked LLM responses for external dependency isolation

### Test Databases

Tests use mocked databases for reliability and speed:
- PostgreSQL: Mocked SQLAlchemy sessions (no real DB connections)
- Redis: Mocked Redis client (no real Redis connections)

## Security Testing Approach

The security tests follow a comprehensive approach:

### Authentication & Authorization
- Password hashing strength and verification
- Session token generation and validation
- Session expiry and hijacking prevention
- User ownership validation for resources

### Input Validation & Sanitization
- SQL injection attempt handling
- XSS attack prevention
- Edge case input validation
- Rate limiting simulation

### Cryptographic Functions
- bcrypt password hashing properties
- Session token randomness and uniqueness
- Hash function collision resistance
- UUID validation for injection prevention

## Writing New Tests

### Security Tests

Security tests should focus on preventing vulnerabilities:

```python
def test_password_hashing_strength():
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
```

### Unit Tests

Unit tests should focus on testing individual functions and classes in isolation:

```python
def test_my_function():
    # Arrange
    input_data = {"key": "value"}
    
    # Act
    result = my_function(input_data)
    
    # Assert
    assert result["expected_key"] == "expected_value"
```

### Agent Evaluation Tests

Agent evaluation tests should focus on AI agent quality and performance:

```python
def test_agent_quality_evaluation():
    """Test agent evaluation framework."""
    evaluator = AgentEvaluator()
    
    # Test with mock agent response
    report = evaluator.evaluate_workflow_agent("Python", "beginner", 5, 4)
    
    # Assert quality metrics
    assert report.quality_metrics.overall_score > 0.8
    assert report.performance_metrics.success is True
    assert report.evaluation_result in [EvaluationResult.EXCELLENT, EvaluationResult.GOOD]
```

### Integration Tests

Integration tests should test multiple components working together:

```python
def test_api_endpoint(client, mock_db):
    # Arrange
    payload = {"title": "Test Roadmap"}
    mock_db.query.return_value.filter.return_value.first.return_value = None
    
    # Act
    response = client.post("/roadmaps", json=payload)
    
    # Assert
    assert response.status_code == 303
```

## Coverage Goals

Current coverage achieves:
- 100% test pass rate - All tests passing
- Comprehensive security coverage - All critical vulnerabilities tested
- Core functionality coverage - Database, API, authentication tested
- LLM integration coverage - Application logic around LLM calls tested
- Agent evaluation coverage - AI agent quality and performance testing
- Validation framework coverage - Content quality and structure validation

## Debugging Tests

### Run with PDB

```bash
uv run pytest --pdb
```

### Stop on First Failure

```bash
uv run pytest -x
```

### Run Specific Test

```bash
uv run pytest tests/unit/test_security.py::TestSecurityUnit::test_password_hashing_strength

# Run agent evaluation test
uv run pytest tests/unit/test_evaluation.py::TestAgentEvaluator::test_evaluate_workflow_agent_success
```

## Continuous Integration

The test suite is designed for CI/CD environments:

- No external dependencies - All external services mocked
- Fast execution - Mocked databases and services
- Reliable results - No flaky tests due to external factors
- Parallel support - Tests can run in parallel
- Coverage reporting - Quality gates and metrics

## Test Quality Standards

- 100% pass rate - All tests must pass
- Clear assertions - Descriptive test failures
- Proper isolation - Tests don't interfere with each other
- Comprehensive coverage - All critical paths tested
- Security focus - Vulnerabilities actively tested and prevented
