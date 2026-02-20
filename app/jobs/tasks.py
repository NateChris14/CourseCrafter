## This task will set generation_runs.status
## update progress in DB
## store a JSON outline string in result_json

import json
from datetime import datetime, timezone
from venv import create

from celery import shared_task
from sqlalchemy import create_engine, exc
from sqlalchemy.orm import sessionmaker

from app.settings import settings
from app.db.models.generation_run import GenerationRun

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

@shared_task(bind=True)
def generate_roadmap_outline(self, run_id: str):
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

