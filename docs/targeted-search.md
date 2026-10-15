# Targeted candidate search across URL pools

The candidate pool holds the user-supplied **software target**. The URL crawl pool holds independent, user-supplied **website home URLs**. A scan pairs one or more targets with one website at job time; it does not create a permanent candidate-to-website relationship.

## Workflow

1. Add candidate names. Optionally set target version, OS and CPU architecture. Leave unknown conditions blank; the system will not guess them.
2. Add public website home URLs to the URL crawl pool. Optionally set a search path template such as `/search?q={query}` and category paths (one per line).
3. Candidate creation and URL pool enablement automatically enqueue eligible candidates against enabled websites. Each candidate checks websites in order; the first `MATCHED` resource ends that candidate's scan and the next queued candidate starts. A URL pool added later is queued for candidates that have not already found a match.
4. Open the Jobs center to see the active website, page progress, attempted websites, matches, versions and installer candidates. A candidate can be promoted to a catalog source only after it has been accepted into Software.

Search starts with the site's `robots.txt` policy. The engine uses these seed and discovery strategies:

- Sitemap URLs named by `robots.txt`, or `/sitemap.xml`; nested sitemap indexes are bounded. Only relevant same-site URLs enter the priority queue.
- GET search forms discovered on the homepage, or the website's configured search path template. POST forms and login flows are not submitted.
- User-configured category paths, category and pagination links, and target-related links. URLs are scored before visiting.
- Optional Google Programmable Search JSON API results, restricted to the configured website via `siteSearch`. Configure `GOOGLE_CSE_API_KEY` and `GOOGLE_CSE_CX` in `.env`; without both, this strategy is disabled. It uses the [official API](https://developers.google.com/custom-search/v1/reference/rest/v1/cse/list), not search-engine HTML scraping.
- Optional AI page-role assistance for ambiguous pages. Set `AI_PAGE_RECOGNITION_ENABLED=true`, `OPENAI_API_KEY`, and `AI_PAGE_MODEL` in `.env`. It sends a short public page excerpt only when the rule classifier returns OTHER and a target name appears in the title or H1, at most five calls per job. The [OpenAI Responses structured output API](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses) supplies a role suggestion; it cannot authorize a URL, mark an artifact verified, or import data. Default is disabled.

The role classifier labels pages HOME, SEARCH_RESULTS, CATEGORY, DETAIL, DOWNLOAD or OTHER. Target name must appear in a detail/download page title or H1 before extraction. `GenericHtmlAdapter` supplies release, artifact and download-link candidates; target version, OS and architecture filter the result. A page with missing evidence is marked `REVIEW_REQUIRED`, not a verified match. Extracted data remains a preview until a user creates a software source and imports its discovery.

`max_pages` is a **per-run request budget**, not the sole stopping rule or a lifetime limit. Automatic scans continue from the saved checkpoint when a request budget is reached; the crawler also stops when a resource matches, the priority frontier is exhausted, or it makes no progress. **Pause** is cooperative and takes effect after the current HTTP request. **Resume** continues from the checkpoint. A backend restart automatically resumes interrupted automatic candidate searches from their checkpoint; manually started legacy URL-pool scans remain paused for review. Candidate target conditions and the URL pool list are snapshotted in the job payload. Spider Job concurrency is fixed at one, including source discovery and release checks, so they wait behind the active task.

Safety boundaries: HTTP/HTTPS only, DNS and private-address checks by `SpiderHttpClient`, same-site page traversal, robots policy, request delay, bounded response sizes and bounded queue. No login bypass, CAPTCHA handling, proxy evasion, or full installer download occurs in this search engine.

## Extension points

`PoolSiteAdapter` provides `search`, `classify` and `priority`; register an adapter for a host in `site_adapters` rather than putting vendor conditions in the crawler. Site search templates and category paths cover simpler sites without code. `ExternalSearchProvider` is injectable, with the Google implementation optional. `AIPageRecognizer` is injectable, with the OpenAI implementation optional. Keep final extraction and import review in the existing adapter/service layer.

## Current limits

One scan accepts at most 50 candidate targets and one cross-site action accepts at most 50 enabled websites. The queue stores at most 2,500 URLs and reads at most 3,000 sitemap page URLs to bound resources. Search forms must support GET or have an explicit search path template. Dynamic JavaScript search, login-only pages and private sites require a separate, authorized adapter; the engine does not bypass site controls.
