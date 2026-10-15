import httpx

from app.core.config import settings
from app.spider.external_search import GoogleProgrammableSearch


def test_official_search_api_filters_other_sites(monkeypatch):
    monkeypatch.setattr(settings, "google_cse_api_key", "test-key")
    monkeypatch.setattr(settings, "google_cse_cx", "test-engine")

    def handler(request):
        assert request.url.host == "customsearch.googleapis.com"
        assert request.url.params["siteSearch"] == "example.test"
        assert request.url.params["q"] == "FusionTestTool"
        return httpx.Response(200, json={"items": [
            {"link": "https://example.test/post/FusionTestTool"},
            {"link": "https://other.test/post/FusionTestTool"},
        ]})

    provider = GoogleProgrammableSearch(httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.discover("example.test", "FusionTestTool") == ["https://example.test/post/FusionTestTool"]
