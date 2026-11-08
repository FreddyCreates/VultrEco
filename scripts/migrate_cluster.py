"""Explicit migration command; no schema mutations in public HTTP request paths."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cluster_queue import Queue

if __name__=="__main__":
    queue=Queue()
    queue.migrate()
    from finance_rails import Receivables
    Receivables(queue).migrate()
    print("CAPSULA cluster PostgreSQL schema installed")
