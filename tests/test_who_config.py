"""Env-driven configuration for the deployable package: model backend, index
location, corpus breadth. Defaults are sane; everything is overridable so the
same image runs in WHO's environment without code changes.
"""
from __future__ import annotations

from who_speech import config


def test_llm_backend_defaults_to_claude(monkeypatch):
    monkeypatch.delenv("WHO_LLM_BACKEND", raising=False)
    assert config.llm_backend() == "claude"


def test_llm_backend_reads_env(monkeypatch):
    monkeypatch.setenv("WHO_LLM_BACKEND", "Azure_OpenAI")
    assert config.llm_backend() == "azure_openai"


def test_index_root_is_durable_by_default(monkeypatch):
    monkeypatch.delenv("WHO_INDEX_ROOT", raising=False)
    # The PoC cached indexes in /tmp; a deployable default must not.
    assert not config.index_root().startswith("/tmp")


def test_index_root_reads_env(monkeypatch):
    monkeypatch.setenv("WHO_INDEX_ROOT", "/data/who")
    assert config.index_root() == "/data/who"


def test_index_languages_parse_csv(monkeypatch):
    monkeypatch.setenv("WHO_INDEX_LANGUAGES", "en, fr ,de")
    assert config.index_languages() == ["en", "fr", "de"]


def test_verify_source_defaults_off(monkeypatch):
    monkeypatch.delenv("WHO_VERIFY_SOURCE", raising=False)
    assert config.verify_source() is False


def test_verify_source_reads_env(monkeypatch):
    monkeypatch.setenv("WHO_VERIFY_SOURCE", "1")
    assert config.verify_source() is True
