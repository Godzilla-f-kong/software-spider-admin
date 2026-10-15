import httpx

from app.core.config import settings
from app.spider.ai_page import OpenAIPageRecognizer
from app.spider.pool_search import PageSignal


def test_optional_ai_role_is_structured_and_bounded(monkeypatch):
    monkeypatch.setattr(settings, "ai_page_recognition_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "test-secret")
    monkeypatch.setattr(settings, "ai_page_model", "test-model")

    def handler(request):
        body = __import__("json").loads(request.content)
        assert request.headers["Authorization"] == "Bearer test-secret"
        assert body["store"] is False
        assert body["text"]["format"]["type"] == "json_schema"
        assert len(body["input"][1]["content"]) < 1800
        return httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": '{"role":"DETAIL"}'}]}]})

    recognizer = OpenAIPageRecognizer(httpx.Client(transport=httpx.MockTransport(handler)))
    assert recognizer.classify(PageSignal("OTHER", "App", "App", "x" * 10000)) == "DETAIL"
