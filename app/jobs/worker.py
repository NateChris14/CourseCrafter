#!/usr/bin/env python3
"""
Simple worker process for roadmap generation tasks
"""
import sys
import os
import signal

# Add the app directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.jobs.tasks import process_roadmap_generation_queue

def signal_handler(sig, frame):
    print('Worker shutting down...')
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("Starting roadmap generation worker...")
    try:
        process_roadmap_generation_queue()
    except KeyboardInterrupt:
        print("Worker stopped by user")
    except Exception as e:
        print(f"Worker error: {e}")
        sys.exit(1)
