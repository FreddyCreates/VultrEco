# Measurement contract

Every performance claim must identify environment, hardware, isolation
boundary, number of concurrent agents, offered load, completed work,
latencies, duration, failures and recovery count.

The `scripts/benchmark_cluster.py` script runs concurrent worker **database
clients**, not VMs. It measures actual PostgreSQL claims and fence-checked
completion with per-job latency and total throughput. Its JSON receipt is
labeled `POSTGRESQL_QUEUE_ONLY_NOT_REAL_VM_LOAD`.

A meaningful multi-host result additionally requires:
- at least two independent VM hosts with separately verified host identities;
- each worker running a disposable code container (and separate agent VMs
  for RAH experiments), with budgets, clean secret environment and teardown;
- varied concurrent tasks: Python, browser, agent iteration and file work;
- p50/p95 queue time, execution time, VM spawn time and cold-start time;
- memory and CPU saturation curves, throttling, error/retry rates;
- forced loss of a running host, stale fence rejection, live instance
  reconciliation and no duplicate irreversible side effects;
- reproducible containment probes and network-denial logs.

A database-only green check is explicitly **not** a production performance
certification. Save measured benchmark JSON and cloud receipts separately.
