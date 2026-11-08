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

## Real remote VM acceptance

The optional `scripts/benchmark_multi_vm.py` requires **2–16** distinct HTTPS
worker origins and exact node IDs. Set the configuration in a private
`CAPSULA_LIVE_VM_TARGETS` environment variable containing JSON objects
`{"id":"vm-001","origin":"https://worker1.example","token_env":"CAPSULA_LIVE_TOKEN_FIRST"}`
with a **separate** record for each worker. Set each referenced token environment
variable independently, and `CAPSULA_LIVE_VM_TEST_APPROVED=1` to authorize the
real workload. Never store credentials in source or the JSON declaration.

The benchmark refuses unsafe local/dev workers and checks per-job output,
digest, UID, no root writes, blocked public network, absence of privileged env
variables and live cgroup ceilings. It emits task p50/p95 and per-host evidence.
A failed network/permission check causes a failed release receipt. Its declared
node identity is operator-supplied, not independently attested; corroborate
Vultr instance identities through the cloud API and hypervisor records.
