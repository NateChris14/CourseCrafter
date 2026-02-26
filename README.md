# CourseCrafter

An AI-powered course generation platform.

## Features

- AI-Driven Course Generation: Create comprehensive courses using advanced AI models
- Modular Architecture: Modular-monolithic based design with web API and background workers
- Database Migrations: Alembic-based schema management
- Production Ready: Docker-based deployment with AWS integration
- Scalable: Supports both local development and cloud deployment

## Prerequisites

- Python 3.12+
- Docker & Docker Compose
- PostgreSQL (for local development)
- Redis (for local development)

## Local Development

### Quick Start

```bash
# Clone the repository
git clone https://github.com/NateChris14/CourseCrafter.git
cd CourseCrafter

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start local services (PostgreSQL + Redis)
docker compose -f docker-compose.dev.yml up -d db redis

# Run database migrations
alembic upgrade head

# Start the application
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

### Environment Variables

Create a `.env` file for local development:

```env
# Database
DATABASE_URL=postgresql+psycopg://coursecrafter:coursecrafter@localhost:5432/coursecrafter

# Redis
REDIS_URL=redis://localhost:6379/0

# Application
ENV=dev
SESSION_SECRET=your-secret-key-here

# AI Provider
LLM_PROVIDER=groq
GROQ_API_KEY=your-groq-api-key
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL=llama-3.1-8b-instant

# Ollama (optional)
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3.1
```

### Docker Development

```bash
# Start all services (including web and worker)
docker compose -f docker-compose.dev.yml up -d

# View logs
docker compose -f docker-compose.dev.yml logs -f web

# Stop services
docker compose -f docker-compose.dev.yml down
```

## Architecture

### Services

- Web: FastAPI application serving HTTP requests
- Worker: Background job processor for AI tasks
- Database: PostgreSQL for data persistence
- Redis: Caching and message queue

### Project Structure

```
CourseCrafter/
├── app/
│   ├── agents/           # AI agent implementations
│   ├── auth/             # Authentication logic
│   ├── courses/          # Course management
│   ├── db/               # Database models and migrations
│   ├── deps.py           # Dependencies
│   ├── main.py           # FastAPI application entry
│   ├── routes.py         # API routes
│   └── settings.py       # Configuration
├── .github/workflows/    # CI/CD pipelines
├── tests/                # Test suites
├── docker-compose.dev.yml    # Development compose
├── docker-compose.prod.yml   # Production compose
├── Dockerfile            # Application container
├── alembic.ini           # Database migration config
└── requirements.txt      # Python dependencies
```

## Deployment

### Production Deployment (AWS)

#### Prerequisites

1. AWS Account with appropriate permissions
2. EC2 Instance with Docker and Docker Compose
3. Amazon ECR for container registry
4. Amazon RDS PostgreSQL instance
5. Amazon ElastiCache Redis instance

#### Setup Steps

1. Create AWS Resources:
   ```bash
   # Create ECR repository
   aws ecr create-repository --repository-name coursecrafter
   
   # Create RDS PostgreSQL instance
   # Create ElastiCache Redis instance
   ```

2. Configure GitHub Secrets:
   - AWS_ACCESS_KEY_ID
   - AWS_SECRET_ACCESS_KEY
   - AWS_REGION
   - ECR_REPOSITORY_NAME
   - DATABASE_URL (RDS endpoint)
   - REDIS_URL (ElastiCache endpoint)
   - SESSION_SECRET
   - GROQ_API_KEY

3. Deploy:
   ```bash
   git push main  # Triggers CI/CD pipeline
   ```

#### Production Docker Compose

```bash
# Deploy with production configuration
docker compose -f docker-compose.prod.yml --env-file .env up -d

# View logs
docker compose -f docker-compose.prod.yml logs -f web
```

### CI/CD Pipeline

The project uses GitHub Actions for automated deployment:

1. CI: Runs tests on code changes
2. Build: Creates Docker image and pushes to ECR
3. Deploy: Deploys to EC2 using self-hosted runner

## Testing

```bash
# Run unit tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/unit/test_models_simple.py
```

## Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1

# View migration history
alembic history
```

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| DATABASE_URL | PostgreSQL connection string | Yes |
| REDIS_URL | Redis connection string | Yes |
| SESSION_SECRET | Session encryption key | Yes |
| GROQ_API_KEY | Groq AI API key | Yes |
| ENV | Environment (dev/prod) | Yes |
| LLM_PROVIDER | AI provider (groq/ollama) | No |
| OLLAMA_BASE_URL | Ollama service URL | No |

### Logging

Production logs are sent to Amazon CloudWatch:
- Log Group: `/coursecrafter/prod`
- Streams: web, worker, db, redis, migrate

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Run the test suite
6. Submit a pull request

## API Documentation

Once running, visit:
- Swagger UI: `http://localhost:8080/docs`
- ReDoc: `http://localhost:8080/redoc`

## Monitoring

### Health Checks

- Application: `GET /health`
- Database: PostgreSQL health check in Docker Compose
- Redis: Connection validation

### Logs

- Development: Console output
- Production: CloudWatch Logs

## Security

- Non-root Docker user
- Environment variable secrets
- HTTPS in production
- Database encryption at rest
- Redis authentication

## Troubleshooting

### Common Issues

1. Database Connection:
   ```bash
   # Check PostgreSQL status
   docker compose logs db
   
   # Test connection
   psql "postgresql+psycopg://coursecrafter:coursecrafter@localhost:5432/coursecrafter"
   ```

2. Redis Connection:
   ```bash
   # Check Redis status
   docker compose logs redis
   
   # Test connection
   redis-cli ping
   ```

3. Migration Issues:
   ```bash
   # Check current revision
   alembic current
   
   # Force migration (use with caution)
   alembic stamp head
   ```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For issues and questions:
- Create an issue on GitHub
- Check the troubleshooting section
- Review the API documentation

Built with FastAPI, PostgreSQL, and Redis