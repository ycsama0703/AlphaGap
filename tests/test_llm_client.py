from types import SimpleNamespace

from pipeline import llm_client as llm_mod
from pipeline.config import load_settings


def test_openrouter_provider_uses_selected_model_and_base_url(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL_DEFAULT", "vendor/model-a")
    monkeypatch.setenv("OPENROUTER_MODEL_REASONING", "vendor/model-b")

    settings = load_settings()

    assert settings.llm_base_url == "https://openrouter.ai/api/v1"
    assert settings.llm_model_default == "vendor/model-a"
    assert settings.llm_model_reasoning == "vendor/model-b"
    assert settings.llm_model_brief == "vendor/model-b"


def test_llm_client_uses_provider_reported_cost(monkeypatch):
    request_args = {}

    class FakeCompletions:
        def create(self, **kwargs):
            request_args.update(kwargs)
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, cost=0.00125),
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL_DEFAULT", "vendor/model-a")
    monkeypatch.setattr(llm_mod, "OpenAI", FakeOpenAI)

    client = llm_mod.LLMClient()
    result = client.chat_json(system="system", user="user")

    assert result == {"ok": True}
    assert request_args["model"] == "vendor/model-a"
    assert client.estimate_cost_usd() == 0.00125


def test_text_completion_is_included_in_provider_reported_cost(monkeypatch):
    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, cost=0.002),
                choices=[SimpleNamespace(message=SimpleNamespace(content="markdown"))],
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL_DEFAULT", "vendor/model-a")
    monkeypatch.setattr(llm_mod, "OpenAI", FakeOpenAI)

    client = llm_mod.LLMClient()

    assert client.chat_text(system="system", user="user") == "markdown"
    assert client.estimate_cost_usd() == 0.002


def test_generic_model_override_applies_to_openrouter(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL_DEFAULT", "vendor/model-a")
    monkeypatch.setenv("LLM_MODEL_DEFAULT", "vendor/test-model")

    assert load_settings().llm_model_default == "vendor/test-model"


def test_reasoning_json_length_failure_retries_with_default_model(monkeypatch):
    requests = []

    class FakeCompletions:
        def create(self, **kwargs):
            requests.append(kwargs)
            if len(requests) == 1:
                return SimpleNamespace(
                    usage=SimpleNamespace(prompt_tokens=10, completion_tokens=100),
                    choices=[SimpleNamespace(
                        finish_reason="length",
                        message=SimpleNamespace(content=""),
                    )],
                )
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                choices=[SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content='{"ok": true}'),
                )],
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL_DEFAULT", "vendor/chat")
    monkeypatch.setenv("OPENROUTER_MODEL_REASONING", "vendor/reasoner")
    monkeypatch.delenv("LLM_MODEL_DEFAULT", raising=False)
    monkeypatch.delenv("LLM_MODEL_REASONING", raising=False)
    monkeypatch.setattr(llm_mod, "OpenAI", FakeOpenAI)

    result = llm_mod.LLMClient().chat_json(
        system="system", user="user", reasoning=True, max_tokens=12345,
    )

    assert result == {"ok": True}
    assert [call["model"] for call in requests] == ["vendor/reasoner", "vendor/chat"]
    assert all(call["max_tokens"] == 12345 for call in requests)


def test_deepseek_routes_daily_to_flash_and_brief_to_pro_with_costs(monkeypatch):
    requests = []

    class FakeCompletions:
        def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=1_000_000),
                choices=[SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content='{"ok": true}'),
                )],
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL_DEFAULT", "deepseek-v4-flash")
    monkeypatch.setenv("DEEPSEEK_MODEL_REASONING", "deepseek-v4-flash")
    monkeypatch.setenv("DEEPSEEK_MODEL_BRIEF", "deepseek-v4-pro")
    monkeypatch.delenv("LLM_MODEL_DEFAULT", raising=False)
    monkeypatch.delenv("LLM_MODEL_REASONING", raising=False)
    monkeypatch.delenv("LLM_MODEL_BRIEF", raising=False)
    monkeypatch.delenv("LLM_INPUT_COST_PER_M", raising=False)
    monkeypatch.delenv("LLM_OUTPUT_COST_PER_M", raising=False)
    monkeypatch.delenv("LLM_REASONING_INPUT_COST_PER_M", raising=False)
    monkeypatch.delenv("LLM_REASONING_OUTPUT_COST_PER_M", raising=False)
    monkeypatch.delenv("LLM_BRIEF_INPUT_COST_PER_M", raising=False)
    monkeypatch.delenv("LLM_BRIEF_OUTPUT_COST_PER_M", raising=False)
    monkeypatch.setattr(llm_mod, "OpenAI", FakeOpenAI)

    client = llm_mod.LLMClient()
    client.chat_json(system="system", user="routine")
    client.chat_json(system="system", user="research", reasoning=True)
    client.chat_text(system="system", user="deep brief", brief=True)

    assert requests[0]["model"] == "deepseek-v4-flash"
    assert requests[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert requests[0]["temperature"] == 0.0
    assert requests[1]["model"] == "deepseek-v4-flash"
    assert requests[1]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "temperature" not in requests[1]
    assert requests[2]["model"] == "deepseek-v4-pro"
    assert requests[2]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert client.estimate_cost_usd() == 2.145


def test_deepseek_reasoning_retry_falls_back_to_non_thinking_flash(monkeypatch):
    requests = []

    class FakeCompletions:
        def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
                choices=[SimpleNamespace(
                    finish_reason="length" if len(requests) == 1 else "stop",
                    message=SimpleNamespace(
                        content="" if len(requests) == 1 else '{"ok": true}'
                    ),
                )],
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL_DEFAULT", "deepseek-v4-flash")
    monkeypatch.setenv("DEEPSEEK_MODEL_REASONING", "deepseek-v4-pro")
    monkeypatch.delenv("LLM_MODEL_DEFAULT", raising=False)
    monkeypatch.delenv("LLM_MODEL_REASONING", raising=False)
    monkeypatch.setattr(llm_mod, "OpenAI", FakeOpenAI)

    result = llm_mod.LLMClient().chat_json(
        system="system", user="user", reasoning=True,
    )

    assert result == {"ok": True}
    assert [request["model"] for request in requests] == [
        "deepseek-v4-pro", "deepseek-v4-flash",
    ]
    assert [
        request["extra_body"]["thinking"]["type"] for request in requests
    ] == ["enabled", "disabled"]


def test_deepseek_flash_reasoning_failure_retries_flash_without_thinking(monkeypatch):
    requests = []

    class FakeCompletions:
        def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
                choices=[SimpleNamespace(
                    finish_reason="length" if len(requests) == 1 else "stop",
                    message=SimpleNamespace(
                        content="" if len(requests) == 1 else '{"ok": true}'
                    ),
                )],
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL_DEFAULT", "deepseek-v4-flash")
    monkeypatch.setenv("DEEPSEEK_MODEL_REASONING", "deepseek-v4-flash")
    monkeypatch.delenv("LLM_MODEL_DEFAULT", raising=False)
    monkeypatch.delenv("LLM_MODEL_REASONING", raising=False)
    monkeypatch.setattr(llm_mod, "OpenAI", FakeOpenAI)

    result = llm_mod.LLMClient().chat_json(
        system="system", user="user", reasoning=True,
    )

    assert result == {"ok": True}
    assert [request["model"] for request in requests] == [
        "deepseek-v4-flash", "deepseek-v4-flash",
    ]
    assert [
        request["extra_body"]["thinking"]["type"] for request in requests
    ] == ["enabled", "disabled"]
