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
