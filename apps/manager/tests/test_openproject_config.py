import pytest
from modules.product_owner.openproject.config import (
    ProjectConfig,
    get_openproject_config,
)


class TestGetOpenprojectConfig:
    """Tests for get_openproject_config()."""

    def test_loads_config_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return ProjectConfig populated from environment variables."""
        monkeypatch.setenv("OPENPROJECT_API_KEY", "test-key-123")
        monkeypatch.setenv(
            "OPENPROJECT_URL", "https://openproject.example.com"
        )

        config = get_openproject_config()

        assert isinstance(config, ProjectConfig)
        assert config.api_key == "test-key-123"
        assert config.base_url == "https://openproject.example.com"
        assert config.team_emails == {}

    def test_raises_when_api_key_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should raise ValueError when OPENPROJECT_API_KEY is not set."""
        monkeypatch.delenv("OPENPROJECT_API_KEY", raising=False)
        monkeypatch.setenv(
            "OPENPROJECT_URL", "https://openproject.example.com"
        )

        with pytest.raises(ValueError, match="OPENPROJECT_API_KEY"):
            get_openproject_config()

    def test_raises_when_url_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should raise ValueError when OPENPROJECT_URL is not set."""
        monkeypatch.setenv("OPENPROJECT_API_KEY", "test-key-123")
        monkeypatch.delenv("OPENPROJECT_URL", raising=False)

        with pytest.raises(ValueError, match="OPENPROJECT_URL"):
            get_openproject_config()

    def test_raises_when_both_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should raise on the first missing variable when both are absent."""
        monkeypatch.delenv("OPENPROJECT_API_KEY", raising=False)
        monkeypatch.delenv("OPENPROJECT_URL", raising=False)

        with pytest.raises(ValueError) as exc:
            get_openproject_config()

        assert "OPENPROJECT_API_KEY" in str(exc.value)
