from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = PROJECT_ROOT / "profiles"

# The Blogsterizer cleans Dyalog blog content. There is one rule set and the
# interface does not ask the user to choose between profiles (handoff 19).
DEFAULT_PROFILE_ID = "blog"


class ProfileError(ValueError):
    pass


def list_profiles() -> list[dict[str, str]]:
    profiles: list[dict[str, str]] = []
    for path in sorted(PROFILE_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        profiles.append({"id": path.stem, "name": data.get("name", path.stem)})
    return profiles


def load_profile(profile_id: str) -> dict[str, Any]:
    safe_id = "".join(ch for ch in profile_id if ch.isalnum() or ch in {"-", "_"})
    path = PROFILE_DIR / f"{safe_id}.yaml"
    if not path.exists():
        raise ProfileError(f"Unknown profile: {profile_id}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ProfileError(f"Profile {profile_id} is not a mapping")
    return data
