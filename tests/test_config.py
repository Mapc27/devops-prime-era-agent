"""TC-10: validator must come from a different model family than every worker."""
import copy

import pytest
import yaml

from opscrew.config import REPO, ConfigError, validate_families


def cfg():
    return yaml.safe_load((REPO / "config/models.yaml").read_text())


def test_shipped_config_is_cross_family():
    validate_families(cfg())


def test_same_family_validator_rejected():
    c = copy.deepcopy(cfg())
    c["roles"]["validator"]["family"] = c["roles"]["heavy"]["family"]
    with pytest.raises(ConfigError):
        validate_families(c)
