---
name: bad-deploy-rollback
description: 'Service crash-loops or fails right after a deploy / config change, nginx 502, ServiceDown alert'
when_to_use: '"after the deploy", startup failed, config error, missing field, exit code != 0 on start'
---
# Bad deploy → rollback

1. `list_services` — which service is exited/restarting; exit code.
2. `query_logs(service, contains="error")` — startup error (missing field, validation error, config error).
3. `query_metrics('app_config_version')` — confirm the version changed at incident start.
4. Mitigation first: roll back, investigate the bad config later.

**Typical fix:** `rollback_config`. Then verify that the service is running and 5xx rate dropped.
