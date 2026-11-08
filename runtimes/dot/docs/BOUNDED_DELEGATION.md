# Bounded mission autonomy

The owner authorizes an objective, assigned workers, deadline and shared resource reservations once. Workers can execute their assignments and, only when explicitly granted, propose recursive child work. Every worker uses a distinct existing agent VM. This release does not silently allocate paid infrastructure, reuse one VM for different child agents or multiply subscription quotas.

## Fixed team missions

`POST /api/missions` accepts 1–8 initial steps. A step names its agent ID, task, timeout, change budget and optional acceptance checks. Dependencies must name earlier steps; cycles are rejected. Independent steps may run concurrently. The dashboard offers a two-worker form; the API supports larger graphs.

The sum of step time/change reservations must fit the mission grant. When a step fails, dependent pending work is cancelled and active sibling work is stopped. Parent revocation is persisted before sending cancellation. Step request keys recover dispatch identity across controller restarts.

Dependency reports pass as explicitly untrusted text. Workspaces and files remain separate; automatic cross-VM artifact transfer is not implemented.

## Recursive child proposals

At mission creation, the owner may add:

```json
{
  "delegation": {
    "agent_pool": ["PREPROVISIONED_CHILD_AGENT_ID", "ANOTHER_CHILD_AGENT_ID"],
    "max_depth": 2,
    "max_children": 2
  }
}
```

The same mission's `limits.task_seconds` and `limits.max_changed_bytes` must leave room for these children after initial reservations. Depth is limited to three and child count to eight. A pool member cannot also be an initial worker, and a VM can be reserved only once in a graph. The pool must already be provisioned and signed in; the source does not create provider credentials for a child.

Inside a running task, the agent can execute:

```bash
python3 /opt/dot/delegation.py --agent APPROVED_CHILD_AGENT_ID \
  --prompt "Implement this independent subproblem" --timeout 120 --changed-bytes 1048576
```

The helper writes a bounded proposal into the parent job's outbox using `DOT_JOB_ID`. It carries no owner token. The host polls proposals over the existing SSH channel and checks pool membership, unique VM reservation, maximum depth, remaining shared budgets and deadline before adding a child step. Invalid proposals are denied with recorded reasons. Proposal identity and reservations persist before dispatch, preventing duplicate child execution on replay.

Children may propose grandchildren within the same grant. They cannot expand the VM pool, reset depth, increase budgets, grant themselves host access or extend the parent deadline. The child job lease inherits the parent's absolute deadline and the guest limits execution accordingly.

New child work has no automatic authority to deploy externally or retrieve another VM's provider credentials. It receives its own assigned VM's ordinary agent-user execution boundary. Child acceptance defaults to provider completion unless the owner supplied a fixed-step acceptance contract; recursive child proposals do not currently carry independent acceptance criteria. The parent/operator must inspect those outputs.

The graph scheduler is source-tested with test backends. These tests establish authorization, reservation and recovery behavior; they do not establish a live multi-VM inference run. The release remains PARTIAL until real-host acceptance and isolation checks pass.
