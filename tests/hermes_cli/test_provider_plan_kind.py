from hermes_cli.providers import provider_plan_kind


def test_provider_plan_kind_marks_known_coding_slugs():
    assert provider_plan_kind("openai-codex") == "coding"
    assert provider_plan_kind("stepfun") == "coding"
    assert provider_plan_kind("alibaba-coding-plan") == "coding"
    assert provider_plan_kind("minimax-oauth") == "coding"


def test_provider_plan_kind_detects_coding_urls():
    assert provider_plan_kind("zai", "https://api.z.ai/api/coding/paas/v4") == "coding"
    assert provider_plan_kind("custom:dashscope", "https://coding-intl.dashscope.aliyuncs.com/v1") == "coding"
    assert provider_plan_kind("custom:kimi", "https://api.kimi.com/coding") == "coding"
    assert provider_plan_kind("zai", "https://api.z.ai/api/paas/v4") == "api"
    assert provider_plan_kind("kimi-coding", "https://api.moonshot.ai/v1") == "api"
