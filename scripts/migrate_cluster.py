"""Explicit migration command; no schema mutations in public HTTP request paths."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cluster_queue import Queue

if __name__=="__main__":
    Queue().migrate()
    print("CAPSULA cluster PostgreSQL schema installed")
