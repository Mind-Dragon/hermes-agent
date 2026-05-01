"""Tests for /model picker type-to-search ranking."""

from cli import HermesCLI


class TestModelPickerSearch:
    def test_empty_provider_query_preserves_order(self):
        providers = [
            {"name": "Nous Portal", "slug": "nous", "models": []},
            {"name": "Kimi For Coding", "slug": "kimi-coding", "models": []},
        ]

        rows = HermesCLI._filter_model_picker_providers("", providers)

        assert [row["provider"]["slug"] for row in rows] == ["nous", "kimi-coding"]

    def test_provider_name_prefix_beats_child_model_substring(self):
        providers = [
            {"name": "OpenRouter", "slug": "openrouter", "models": ["moonshotai/kimi-k2.5"]},
            {"name": "Kimi For Coding", "slug": "kimi-coding", "models": ["kimi-k2.6-FCED"]},
            {"name": "Kimi For Coding", "slug": "kimi-coding-cn", "models": ["kimi-k2.6-cn"]},
        ]

        rows = HermesCLI._filter_model_picker_providers("kimi", providers)

        assert [row["provider"]["slug"] for row in rows] == [
            "kimi-coding",
            "kimi-coding-cn",
            "openrouter",
        ]

    def test_provider_search_matches_child_model_ids(self):
        providers = [
            {"name": "Nous Portal", "slug": "nous", "models": ["deepseek/deepseek-v3"]},
            {"name": "OpenRouter", "slug": "openrouter", "models": ["openai/gpt-5.5"]},
        ]

        rows = HermesCLI._filter_model_picker_providers("gpt55", providers)

        assert [row["provider"]["slug"] for row in rows] == ["openrouter"]

    def test_model_prefix_substring_fuzzy_order(self):
        models = ["openai/not-kimi", "kimi-k2.6-FCED", "k-x-i-m-i-test"]

        rows = HermesCLI._filter_model_picker_models("kimi", models)

        assert [row["model"] for row in rows] == ["kimi-k2.6-FCED", "openai/not-kimi", "k-x-i-m-i-test"]

    def test_model_search_matches_across_separators(self):
        models = ["openai/gpt-5.5", "openai/gpt-4.1"]

        rows = HermesCLI._filter_model_picker_models("gpt55", models)

        assert [row["model"] for row in rows] == ["openai/gpt-5.5"]

    def test_model_search_rejects_non_matches(self):
        assert HermesCLI._rank_model_picker_text("zzzz", ["kimi-k2.6-FCED"]) is None
