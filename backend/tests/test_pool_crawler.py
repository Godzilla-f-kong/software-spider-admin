import httpx

from app.core.enums import CandidateStatus
from app.models import CrawlPool
from app.spider.http import SpiderHttpClient
from app.spider.pool_crawler import CandidateTarget, PoolCrawler


def test_homepage_crawl_finds_user_candidate_on_internal_article():
    seen = []
    def handler(request):
        seen.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.path == "/":
            return httpx.Response(200, headers={"content-type": "text/html"}, text='''
                <title>Software site</title>
                <a href="https://other.test/FusionTestTool">External</a>
                <a href="/post/137.html">FusionTestTool v3.2</a>
                <a href="/post/other.html">Other software</a>''')
        if request.url.path == "/post/137.html":
            return httpx.Response(200, headers={"content-type": "text/html"}, text='''
                <title>FusionTestTool v3.2 - Software site</title><h1>FusionTestTool v3.2</h1>
                <a href="https://cdn.test/FusionTestTool-3.2-x64.zip">Download ZIP</a>''')
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>Other software</title>")
    http = SpiderHttpClient(transport=httpx.MockTransport(handler), allow_private=True, delay=0, retries=0)
    pool = CrawlPool(base_url="https://example.test/", max_pages=3, max_depth=1)
    candidate = CandidateTarget(7, "FusionTestTool", "fusiontesttool", CandidateStatus.DISCOVERED)
    try:
        result = PoolCrawler(http).scan(pool, [candidate])
    finally:
        http.close()
    assert result["visited_pages"] == 3
    assert len(result["matches"]) == 1
    assert result["matches"][0]["candidate_id"] == 7
    assert result["matches"][0]["page_url"] == "https://example.test/post/137.html"
    assert result["matches"][0]["artifact_count"] == 1
    assert result["matches"][0]["versions"] == ["3.2"]
    assert not any("other.test" in url for url in seen)


def test_homepage_teaser_is_not_mistaken_for_software_page():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text='<title>Home</title><a href="/post/app.html">FusionTestTool</a>')
    http = SpiderHttpClient(transport=httpx.MockTransport(handler), allow_private=True, delay=0, retries=0)
    pool = CrawlPool(base_url="https://example.test/", max_pages=1, max_depth=1)
    try:
        result = PoolCrawler(http).scan(pool, [CandidateTarget(7, "FusionTestTool", "fusiontesttool", CandidateStatus.DISCOVERED)])
    finally:
        http.close()
    assert result["matches"] == []
    assert result["limit_reached"] is True


def test_automatic_search_stops_visiting_site_after_first_confirmed_match():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.path == "/sitemap.xml":
            return httpx.Response(404)
        if request.url.path == "/":
            return httpx.Response(200, headers={"content-type": "text/html"}, text='''
                <title>Tools</title>
                <a href="/post/app.html">AutoSearchTool release</a>
                <a href="/post/other.html">Unrelated article</a>''')
        if request.url.path == "/post/app.html":
            return httpx.Response(200, headers={"content-type": "text/html"}, text='''
                <title>AutoSearchTool 1.2</title><h1>AutoSearchTool</h1>
                <a href="https://cdn.example.test/AutoSearchTool-1.2-x64.zip">Windows x64 ZIP</a>''')
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>Unrelated</title>")

    http = SpiderHttpClient(transport=httpx.MockTransport(handler), allow_private=True, delay=0, retries=0)
    try:
        result = PoolCrawler(http).scan(
            CrawlPool(base_url="https://example.test/", max_pages=20, max_depth=2),
            [CandidateTarget(8, "AutoSearchTool", "autosearchtool", CandidateStatus.DISCOVERED)],
            stop_on_match=True)
    finally:
        http.close()

    assert result["stop_reason"] == "MATCH_FOUND"
    assert len(result["matches"]) == 1
    assert "/post/other.html" not in seen


def test_search_form_beats_unrelated_home_links_and_resumes_from_checkpoint():
    seen = []
    def handler(request):
        seen.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.path == "/sitemap.xml":
            return httpx.Response(404)
        if request.url.path == "/":
            return httpx.Response(200, headers={"content-type": "text/html"}, text='''
                <title>Home</title><form method="get" action="/find"><input name="keyword" type="search"></form>
                <a href="/post/unrelated.html">Unrelated</a>''')
        if request.url.path == "/find":
            assert request.url.params["keyword"] == "FusionTestTool"
            return httpx.Response(200, headers={"content-type": "text/html"},
                text='<title>Search results</title><a href="/post/tool.html">FusionTestTool</a>')
        if request.url.path == "/post/tool.html":
            return httpx.Response(200, headers={"content-type": "text/html"},
                text='<title>FusionTestTool 3.2</title><h1>FusionTestTool 3.2</h1>'
                     '<a href="https://cdn.test/FusionTestTool-3.2-win-x64.zip">Download</a>')
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>Other</title>")
    http = SpiderHttpClient(transport=httpx.MockTransport(handler), allow_private=True, delay=0, retries=0)
    pool = CrawlPool(base_url="https://example.test/", max_pages=1, max_depth=3)
    target = CandidateTarget(7, "FusionTestTool", "fusiontesttool", CandidateStatus.DISCOVERED,
                             "3.2", None, None)
    try:
        first = PoolCrawler(http).scan(pool, [target])
        assert first["stop_reason"] == "BUDGET"
        assert first["checkpoint"]
        pool.max_pages = 3
        second = PoolCrawler(http).scan(pool, [target], checkpoint=first["checkpoint"])
    finally:
        http.close()
    assert second["matches"][0]["match_status"] == "MATCHED"
    assert second["matches"][0]["versions"] == ["3.2"]
    assert seen.index("https://example.test/find?keyword=FusionTestTool") < seen.index("https://example.test/post/unrelated.html") if "https://example.test/post/unrelated.html" in seen else True


def test_sitemap_target_seed_and_robots_boundary():
    seen = []
    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\nSitemap: https://example.test/sitemap.xml")
        if request.url.path == "/sitemap.xml":
            return httpx.Response(200, headers={"content-type": "application/xml"}, text='''
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://example.test/post/FusionTestTool.html</loc></url>
                  <url><loc>https://example.test/private/FusionTestTool.html</loc></url>
                </urlset>''')
        if request.url.path == "/post/FusionTestTool.html":
            return httpx.Response(200, headers={"content-type": "text/html"},
                text='<title>FusionTestTool</title><h1>FusionTestTool</h1>'
                     '<a href="https://cdn.test/FusionTestTool-win64.zip">Download</a>')
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>Home</title>")
    http = SpiderHttpClient(transport=httpx.MockTransport(handler), allow_private=True, delay=0, retries=0)
    try:
        result = PoolCrawler(http).scan(CrawlPool(base_url="https://example.test/", max_pages=3, max_depth=2),
            [CandidateTarget(7, "FusionTestTool", "fusiontesttool", CandidateStatus.DISCOVERED)])
    finally:
        http.close()
    assert result["matches"] and result["strategies"].get("SITEMAP") == 1
    assert "/private/FusionTestTool.html" not in seen


def test_target_version_mismatch_requires_review():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.path == "/sitemap.xml":
            return httpx.Response(404)
        if request.url.path == "/":
            return httpx.Response(200, headers={"content-type": "text/html"}, text='<a href="/post/app.html">FusionTestTool</a>')
        return httpx.Response(200, headers={"content-type": "text/html"},
            text='<title>FusionTestTool 3.2</title><h1>FusionTestTool 3.2</h1><a href="https://cdn.test/app-win-x64.zip">Download</a>')
    http = SpiderHttpClient(transport=httpx.MockTransport(handler), allow_private=True, delay=0, retries=0)
    try:
        result = PoolCrawler(http).scan(CrawlPool(base_url="https://example.test/", max_pages=2, max_depth=2),
            [CandidateTarget(7, "FusionTestTool", "fusiontesttool", CandidateStatus.DISCOVERED, "9.9")])
    finally:
        http.close()
    assert result["matches"][0]["match_status"] == "REVIEW_REQUIRED"


def test_cross_site_redirect_is_not_fetched():
    seen = []
    def handler(request):
        seen.append(request.url.host)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.path == "/sitemap.xml":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "https://outside.test/landing"})
    http = SpiderHttpClient(transport=httpx.MockTransport(handler), allow_private=True, delay=0, retries=0)
    try:
        from app.spider.errors import SpiderError
        import pytest
        with pytest.raises(SpiderError, match="Redirect left the configured website"):
            PoolCrawler(http).scan(CrawlPool(base_url="https://example.test/", max_pages=1, max_depth=1),
                [CandidateTarget(7, "FusionTestTool", "fusiontesttool", CandidateStatus.DISCOVERED)])
    finally:
        http.close()
    assert "outside.test" not in seen
