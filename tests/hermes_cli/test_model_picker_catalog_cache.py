"""Tests for the /model picker catalog cache and autocomplete hot path."""

from __future__ import annotations

import json
import time

from hermes_cli.commands import SlashCommandCompleter


def test_model_completion_long_query_uses_cached_preview_without_live_catalog(monkeypatch):
    """Typing common long queries like gpt55 must not fan out to live /models."""

    providers = [
        {
            "slug": "openai",
            "name": "OpenAI",
            "models": ["gpt-5.5", "gpt-4.1-mini"],
            "total_models": 2,
            "plan": "api",
        },
        {
            "slug": "kimi-coding",
            "name": "Kimi for Coding",
            "models": ["kimi-k2.6"],
            "total_models": 1,
            "plan": "coding",
        },
    ]

    monkeypatch.setattr(
        "hermes_cli.model_picker_catalog_cache.prime_model_picker_catalog_cache",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "hermes_cli.model_picker_catalog_cache.get_model_picker_providers_cached",
        lambda **_kwargs: providers,
    )

    def fail_live_catalog(provider, *args, **kwargs):  # pragma: no cover - assertion path
        raise AssertionError(f"unexpected live model catalog lookup for {provider}")

    monkeypatch.setattr("hermes_cli.models.provider_model_ids", fail_live_catalog)

    completions = list(SlashCommandCompleter()._model_completions("gpt55", "gpt55"))

    assert [c.text for c in completions] == ["gpt-5.5"]


def test_model_completion_invalidates_process_cache_when_fingerprint_changes(monkeypatch):
    """A cold new context must not keep returning the previous provider rows."""

    first_rows = [{"slug": "openai", "name": "OpenAI", "models": ["gpt-5.5"]}]
    calls = []

    monkeypatch.setattr(
        "hermes_cli.model_picker_catalog_cache.prime_model_picker_catalog_cache",
        lambda **_kwargs: None,
    )

    def fake_rows(**_kwargs):
        calls.append("rows")
        return first_rows if len(calls) == 1 else []

    statuses = iter([
        {"fingerprint": "first", "cached": True, "refreshing": False},
        {"fingerprint": "second", "cached": False, "refreshing": True},
    ])
    monkeypatch.setattr(
        "hermes_cli.model_picker_catalog_cache.get_model_picker_providers_cached",
        fake_rows,
    )
    monkeypatch.setattr(
        "hermes_cli.model_picker_catalog_cache.get_model_picker_catalog_status",
        lambda **_kwargs: next(statuses),
    )

    completer = SlashCommandCompleter()

    assert completer._model_provider_rows() == first_rows
    assert completer._model_provider_rows() == []


def test_model_picker_catalog_cache_returns_stale_rows_while_background_refresh_runs(tmp_path):
    """A stale cache entry should render immediately and refresh out of band."""

    from hermes_cli.model_picker_catalog_cache import ModelPickerCatalogCache

    cache = ModelPickerCatalogCache(
        cache_path=tmp_path / "model_picker_catalog.json",
        stale_after_seconds=0,
        usable_for_seconds=3600,
    )
    fingerprint = "provider-fingerprint"
    stale_rows = [{"slug": "openai", "name": "OpenAI", "models": ["gpt-4.1"]}]
    fresh_rows = [{"slug": "openai", "name": "OpenAI", "models": ["gpt-5.5"]}]
    cache.store(fingerprint, stale_rows, fetched_at=time.time() - 120)

    calls = []

    def refresh():
        calls.append("refresh")
        return fresh_rows

    rows = cache.get_or_refresh(fingerprint, refresh, background=True)

    assert rows == stale_rows
    assert calls in ([], ["refresh"])

    cache.wait_for_refresh(fingerprint, timeout=2)

    assert calls == ["refresh"]
    assert cache.get_cached(fingerprint) == fresh_rows


def test_model_picker_catalog_cache_merges_entries_from_other_processes(tmp_path):
    """One process storing a warmed key must not erase another process's key."""

    from hermes_cli.model_picker_catalog_cache import ModelPickerCatalogCache

    cache_path = tmp_path / "model_picker_catalog.json"
    first = ModelPickerCatalogCache(cache_path=cache_path)
    second = ModelPickerCatalogCache(cache_path=cache_path)

    # Force both instances to load an initially empty disk snapshot before
    # either writes. This reproduces the cross-process stale-memory clobber.
    assert first.get_cached("missing") is None
    assert second.get_cached("missing") is None

    first.store("first", [{"slug": "openai"}])
    second.store("second", [{"slug": "anthropic"}])

    verifier = ModelPickerCatalogCache(cache_path=cache_path)
    assert verifier.get_cached("first") == [{"slug": "openai"}]
    assert verifier.get_cached("second") == [{"slug": "anthropic"}]


def test_model_picker_catalog_cache_reloads_entries_from_other_processes(tmp_path):
    """A long-lived process should see cache entries warmed by a sibling."""

    from hermes_cli.model_picker_catalog_cache import ModelPickerCatalogCache

    cache_path = tmp_path / "model_picker_catalog.json"
    reader = ModelPickerCatalogCache(cache_path=cache_path)
    writer = ModelPickerCatalogCache(cache_path=cache_path)

    assert reader.get_cached("late") is None
    writer.store("late", [{"slug": "copilot"}])

    assert reader.get_cached("late") == [{"slug": "copilot"}]


def test_model_picker_catalog_fingerprint_tracks_key_env_value(monkeypatch):
    """Changing the env value behind key_env should invalidate the picker cache."""

    from hermes_cli.model_picker_catalog_cache import model_picker_catalog_fingerprint

    provider_cfg = {
        "custom-openai": {
            "name": "Custom OpenAI",
            "base_url": "https://example.test/v1",
            "key_env": "MODEL_PICKER_TEST_KEY",
            "models": ["gpt-test"],
        }
    }

    monkeypatch.setenv("MODEL_PICKER_TEST_KEY", "one")
    first = model_picker_catalog_fingerprint(user_providers=provider_cfg)
    monkeypatch.setenv("MODEL_PICKER_TEST_KEY", "two")
    second = model_picker_catalog_fingerprint(user_providers=provider_cfg)

    assert first != second


def test_model_picker_catalog_fingerprint_tracks_builtin_provider_env(monkeypatch):
    """Built-in API key env changes should also invalidate cached provider rows."""

    from hermes_cli.model_picker_catalog_cache import model_picker_catalog_fingerprint

    monkeypatch.setenv("OPENAI_API_KEY", "one")
    first = model_picker_catalog_fingerprint()
    monkeypatch.setenv("OPENAI_API_KEY", "two")
    second = model_picker_catalog_fingerprint()

    assert first != second


def test_model_picker_catalog_fingerprint_ignores_current_model_fragmentation():
    from hermes_cli.model_picker_catalog_cache import model_picker_catalog_fingerprint

    first = model_picker_catalog_fingerprint(current_provider="openai", current_model="gpt-5.4")
    second = model_picker_catalog_fingerprint(current_provider="openai", current_model="gpt-5.5")
    other_provider = model_picker_catalog_fingerprint(
        current_provider="anthropic",
        current_model="claude-sonnet-4.6",
    )

    assert first == second == other_provider


def test_model_picker_catalog_fingerprint_tracks_auth_store_provider_presence(tmp_path, monkeypatch):
    from hermes_cli.model_picker_catalog_cache import model_picker_catalog_fingerprint

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "version": 1,
                "providers": {},
                "credential_pool": {
                    "copilot": [
                        {
                            "id": "one",
                            "label": "gh auth token",
                            "auth_type": "api_key",
                            "source": "gh_cli",
                            "access_token": "secret-a",
                            "request_count": 0,
                        }
                    ]
                },
                "updated_at": "first",
            }
        ),
        encoding="utf-8",
    )
    first = model_picker_catalog_fingerprint()
    auth_path.write_text(
        json.dumps(
            {
                "version": 1,
                "providers": {},
                "credential_pool": {
                    "copilot": [
                        {
                            "id": "one",
                            "label": "gh auth token",
                            "auth_type": "api_key",
                            "source": "gh_cli",
                            "access_token": "secret-b",
                            "request_count": 99,
                        }
                    ]
                },
                "updated_at": "second",
            }
        ),
        encoding="utf-8",
    )
    volatile_only = model_picker_catalog_fingerprint()
    auth_path.write_text(json.dumps({"version": 1, "providers": {}, "credential_pool": {}}), encoding="utf-8")
    removed_provider = model_picker_catalog_fingerprint()

    assert first == volatile_only
    assert removed_provider != first
