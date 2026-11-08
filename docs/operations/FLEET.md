# CAPSULA worker fleet admission

CAPSULA is a **provider-neutral computer and agent platform**. It supports multiple
registered worker endpoints across private infrastructure, Vultr or other cloud
VMs. The v0.6 RAH/Dot host gives agents dedicated guest VMs; this additional
controller fleet layer schedules per-job Python/browser workers without selecting
the most recently heartbeating host blindly.

## Admission

- Workers register through the existing authenticated, allowlisted `/api/workers` API.
- Each registered worker has a capacity (default 1), provider label, node and region.
- `GET /api/fleet` lists advertised capacity, running slots and available slots.
- `PUT /api/fleet/workers/{id}/capacity` sets limits or marks the worker draining.
- `POST /api/fleet/reconcile` expires stale admission records.
- Mission dispatch takes a serialized slot reservation, sends one job to that
  specific worker, stores the returned result and releases the slot.
- The placement algorithm spreads work by normalized utilization and prior
  assignments. Offline, drained and full workers are skipped.

## Security boundaries

This is an **admission scheduler**, not proof of VM isolation or remote process
termination. After a controller crash, an expired lease may still correspond to
work on the remote machine: worker idempotency, fencing tokens, independent
hypervisor enforcement and remote cancellation are still required before
exposing untrusted public multi-tenant execution. The current SQLite database
is one authoritative controller. A real multi-controller deployment needs a
transactional shared database, queue, fencing and distributed reconciliation.

Vultr compute keys remain only in the operator-controlled provisioning plane.
Worker jobs receive scoped task inputs and never Vultr/GitHub/controller secrets.
No agent can allocate new compute capacity or gain extra budgets simply by
submitting a plan. The Dot VM subsystem remains intact and distinct.
