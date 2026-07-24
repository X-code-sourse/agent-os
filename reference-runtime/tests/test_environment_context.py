"""Tests for Environment Context (SPEC-0010 Layer 6)."""
from __future__ import annotations

from core.environment_context import (
    EnvironmentProfile,
    detect_environment,
    format_environment,
)


class TestDetectEnvironment:
    """detect_environment() basic checks."""

    def test_returns_profile(self) -> None:
        env = detect_environment()
        assert isinstance(env, EnvironmentProfile)
        assert env.runtime_version != ""

    def test_platform_detected(self) -> None:
        env = detect_environment()
        assert env.platform != ""

    def test_python_version_detected(self) -> None:
        env = detect_environment()
        assert env.python_version != ""

    def test_adapters_is_list(self) -> None:
        env = detect_environment()
        assert isinstance(env.available_adapters, list)

    def test_default_adapter_is_set(self) -> None:
        env = detect_environment()
        if env.available_adapters:
            assert env.default_adapter != ""

    def test_tools_is_list(self) -> None:
        env = detect_environment()
        assert isinstance(env.tools, list)
        assert "filesystem_read" in env.tools


class TestFormatEnvironment:
    """format_environment() output."""

    def test_format_returns_string(self) -> None:
        text = format_environment()
        assert isinstance(text, str)
        assert len(text) > 0
        assert "Runtime" in text

    def test_format_includes_adapters(self) -> None:
        env = detect_environment()
        if env.available_adapters:
            text = format_environment(env)
            for a in env.available_adapters:
                assert a in text


class TestEnvironmentProfile:
    """EnvironmentProfile dataclass."""

    def test_defaults(self) -> None:
        p = EnvironmentProfile()
        assert p.available_adapters == []
        assert p.runtime_version == ""
