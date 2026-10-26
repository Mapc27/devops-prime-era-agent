---
name: diagnose-oom
description: 'Container is OOM-killed or restarting in a loop, memory grows to the limit, ContainerRestarting alert'
when_to_use: 'restarts count grows, exit code 137, oom_killed=true, worker crashes, jobs not processed'
---
# Diagnose OOM / restart loops

1. `list_services` — find the service with growing `restarts`, `exit_code=137` or `oom_killed=True`.
2. `inspect_service(service)` — memory usage vs `memory_limit_mb`.
3. `query_logs(service)` — last lines before `Killed`; look for batch/size parameters.
4. `query_metrics('app_config_version')` — was there a deploy (config version change) right before?
5. Correlate: memory per batch × batch_size vs limit.

**Typical fix:** bad config (e.g. huge `worker.batch_size`) → `rollback_config`. Raising the memory limit
is a separate human decision, not an agent action.
