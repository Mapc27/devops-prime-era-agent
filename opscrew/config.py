import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent


@dataclass(frozen=True)
class Settings:
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    mcp_url: str = os.getenv("MCP_URL", "http://localhost:8070/mcp")
    otlp_endpoint: str = os.getenv("OTLP_ENDPOINT", "http://localhost:4317")
    data_dir: Path = Path(os.getenv("OPSCREW_DATA", str(REPO / ".data")))
    models_file: Path = Path(os.getenv("OPSCREW_MODELS", str(REPO / "config/models.yaml")))
    auto_approve: bool = os.getenv("OPSCREW_AUTO_APPROVE", "false").lower() == "true"
    approval_secret: str = os.getenv("APPROVAL_SECRET", "opscrew-approval-secret")
    max_revisions: int = int(os.getenv("OPSCREW_MAX_REVISIONS", "2"))
    max_tool_steps: int = int(os.getenv("OPSCREW_MAX_TOOL_STEPS", "8"))
    tracing: bool = os.getenv("OPSCREW_TRACING", "true").lower() == "true"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def models_cfg() -> dict:
    cfg = yaml.safe_load(settings.models_file.read_text())
    validate_families(cfg)
    return cfg


class ConfigError(RuntimeError):
    pass


def validate_families(cfg: dict) -> None:
    """Cross-family rule: the validator must come from a different model family than every worker."""
    roles = cfg["roles"]
    vf = roles["validator"]["family"]
    worker_fams = {roles[w]["family"] for w in cfg["workers"]}
    if vf in worker_fams:
        raise ConfigError(f"validator family '{vf}' must differ from worker families {sorted(worker_fams)}")
