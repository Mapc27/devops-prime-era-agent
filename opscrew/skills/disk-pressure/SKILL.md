---
name: disk-pressure
description: 'Disk or volume almost full, "No space left on device", uploads fail with 507, DiskAlmostFull alert'
when_to_use: 'disk usage alerts, write errors, OSError ENOSPC'
---
# Disk pressure

1. `run_diagnostic("df -h /mnt/uploads")` — how full is the volume.
2. `run_diagnostic("ls -la /mnt/uploads")` / `run_diagnostic("du -sh /mnt/uploads")` — what is big? Look for
   unexpected `*.tmp` dump files vs regular `*.bin` uploads.
3. `query_logs(service="api", contains="space")` — confirm write failures.
4. `query_metrics('uploads_disk_usage_ratio')` — when did it jump?

**Typical fix:** `cleanup_uploads` (removes *.tmp junk and old uploads beyond the newest 20).
**Never:** `rm -rf` arbitrary paths, delete database files or volumes.
