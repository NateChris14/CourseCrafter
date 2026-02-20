## Simple Redis-based task queue for roadmap generation
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any

import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.settings import settings
from app.db.models.generation_run import GenerationRun

# Redis connection for task queue
redis_client = redis.Redis.from_url(settings.redis_url)

# Database connection
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

def queue_roadmap_generation(run_id: str) -> str:
    """Queue a roadmap generation task and return task ID"""
    task_id = str(uuid.uuid4())
    
    # Add task to Redis queue
    task_data = {
        "task_id": task_id,
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    redis_client.lpush("roadmap_generation_queue", json.dumps(task_data))
    return task_id

def process_roadmap_generation_queue():
    """Process tasks from the queue (this would be run by a worker)"""
    while True:
        try:
            # Get task from queue (blocking)
            _, task_data = redis_client.brpop("roadmap_generation_queue", timeout=30)
            if task_data:
                task = json.loads(task_data)
                generate_roadmap_outline_sync(task["run_id"])
        except Exception as e:
            print(f"Error processing task: {e}")
            continue

def generate_roadmap_outline_sync(run_id: str) -> Dict[str, Any]:
    """Synchronous version of the generation task"""
    db = SessionLocal()
    try:
        run = db.query(GenerationRun).filter(GenerationRun.id == run_id).first()
        if not run:
            return {"ok": False, "error": "run not found"}

        run.status = "running"
        run.progress = 5
        run.message = "Starting generation"
        run.started_at = datetime.now(timezone.utc)
        db.commit()

        # Placeholder logic for now (next step: call Ollama/Groq)
        outline = {
            "weeks": [
                {"week": 1, "title": "Foundations", "outcomes": ["Concepts", "Tooling", "Setup"]},
                {"week": 2, "title": "Core Skills", "outcomes": ["Practice", "Mini project"]},
            ]
        }

        run.progress = 80
        run.message = "Writing results"
        run.result_json = json.dumps(outline)
        db.commit()

        run.status = "succeeded"
        run.progress = 100
        run.message = "Done"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()

        return {"ok": True}
    except Exception as e:
        # Mark failed
        run = db.query(GenerationRun).filter(GenerationRun.id == run_id).first()
        if run:
            run.status = "failed"
            run.error = str(e)
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
        raise
    finally:
        db.close()

