"""TC-15/16: executor allowlist — host files, shell tricks, writes and internet egress are blocked."""
from executor import check


def test_allowed_readonly():
    for c in [["df", "-h"], ["psql", "-c", "SELECT count(*) FROM pg_stat_activity"], ["redis-cli", "ping"],
              ["curl", "-s", "http://api:8000/health"], ["redis-cli", "memory", "stats"]]:
        assert check(c) is None, c


def test_blocked():
    cases = [
        ["cat", "/etc/passwd"],                                   # not in allowlist
        ["sh", "-c", "id"],
        ["curl", "-s", "https://example.com"],                    # egress outside the lab
        ["curl", "-X", "POST", "http://api:8000/upload"],         # write
        ["psql", "-c", "DROP TABLE users"],
        ["psql", "-c", "SELECT pg_terminate_backend(1)"],
        ["redis-cli", "FLUSHALL"],
        ["redis-cli", "config", "set", "maxmemory", "1"],
        ["df", "-h;", "rm", "-rf", "/"],                          # shell metacharacters
    ]
    for c in cases:
        assert check(c) is not None, c
