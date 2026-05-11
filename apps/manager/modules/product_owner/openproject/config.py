import os
from dataclasses import dataclass, field


@dataclass
class ProjectConfig:
    api_key: str
    base_url: str
    team_emails: dict[str, str] = field(default_factory=dict)


def get_openproject_config() -> ProjectConfig:
    api_key = os.environ.get("OPENPROJECT_API_KEY")
    base_url = os.environ.get("OPENPROJECT_URL")

    if not api_key:
        raise ValueError("OPENPROJECT_API_KEY environment variable is not set")
    if not base_url:
        raise ValueError("OPENPROJECT_URL environment variable is not set")

    return ProjectConfig(api_key=api_key, base_url=base_url)
