
# Changelog

All notable changes to the Autonomous B2B Lead Generation Agent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/ "null"), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html "null").

## [2.0.0] - 2026-06-23

_This major release introduces the mathematical entity evaluation engine, fully integrates the Tier 2 headless fallback into the autonomous loop, and drastically refines pipeline synchronization._

### Added

-   **Probabilistic Scoring Engine (H/I/C/D):** Introduced a 4-axis grading model mathematically scoring domains out of 100 based on Hireability (20%), Intent (55%), Clarity (15%), and Commercial Depth (10%).
    
-   **Tier 2 (Playwright) Autonomous Handoff:** Properly implemented the pre-configured Playwright scraper into the active extraction pipeline. The Orchestrator now automatically triggers the headless Chromium fallback when Tier 1 (`httpx`) is blocked by Cloudflare (Score 0.0) or fails to extract contact info, allowing for successful JS DOM hydration.
    
-   **Dynamic Geographic Firewall:** The LLM now actively calculates target regions and generates a tuple of forbidden TLDs (e.g., `.in`, `.pk`) to physically block offshore lead-generation farms.
    
-   **Pipeline Analytics Histogram:** The Orchestrator now generates a visual histogram terminal output of all graded domains (e.g., >90, >80, <50) upon completion.
    

### Changed

-   **Yield Logic:** Removed arbitrary quota caps. The agent now returns _all_ leads discovered in the iterations that score `>= 60.0`, maximizing data yield per run.
    
-   **Playwright Navigation:** Changed `networkidle` to `wait_until="load"` + `1500ms` timeout, drastically reducing Tier 2 extraction time while still allowing SPA DOM hydration.
    
-   **LLM Search Strategy:** Shifted LLM from generating "entity names" to generating strict DuckDuckGo Boolean queries (Commercial Footprints) to force exact-match B2B results.
    

### Fixed

-   **Root Domain Deduplication:** Upgraded the `seen_domains` set using `urllib.parse` to strip `www.`, subdirectories, and HTTP protocols, preventing the same company from being extracted twice.
    
-   **LLM Congestion Crashes:** Added explicit `KeyError` try/except handling to allow the Orchestrator to survive and retry when the upstream OpenRouter API times out or drops the connection.
    
-   **Tier 2 Ghosting:** Fixed a bug where HTML fetched by Playwright was bypassing the probabilistic scoring engine. Playwright DOMs are now strictly graded through the H/I/C/D logic.
    

## [1.0.0] - 2026-06-20

### Added

-   Asynchronous Python orchestrator utilizing DuckDuckGo for concurrent link harvesting, perfectly synchronized using `asyncio.wait(return_when=FIRST_COMPLETED)` to properly race `queue.join()` against a global kill switch without starving background tasks.
    
-   **Priority Queue:** Search results are ingested and sorted by Search Engine Rank, forcing asynchronous workers to process high-quality blue-chip domains before low-quality results.
    
-   Hard array slice limits (`[:MAX_PARALLEL_SEARCHES]`) on LLM JSON parsing to preemptively block hallucination query spam.
    
-   6-Step regex and BeautifulSoup HTML parser for email and E.164 phone extraction (Mailto, Tel, Cloudflare decode, JSON-LD, Semantic blocks, Raw Regex).
    
-   Basic LLM integration for search query generation.
    
-   Configured (but unlinked) Playwright headless browser script.
    
-   CSV export module.