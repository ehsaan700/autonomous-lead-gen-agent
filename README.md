
# 🤖 Autonomous B2B Lead Generation Agent

An enterprise-grade, fully autonomous AI agent that leverages LLM reasoning to dynamically formulate search strategies, asynchronously scrape the web, and extract validated B2B contact data.

Unlike traditional linear scrapers, this system utilizes a highly concurrent Orchestrator to manage worker threads, bypass anti-bot protections, and guarantee data quality.

## 🌟 Core Architecture

-   **The Cognitive Layer (ReAct Loop):** Driven by an LLM (via OpenRouter), the agent dynamically calculates lead deficits and generates hyper-targeted Boolean search queries (e.g., `intitle:"PR agency" "Dallas" "press release"`).
    
-   **Asynchronous Priority Queue:** Search results are ingested into an `asyncio.PriorityQueue` tagged by their original Search Engine Rank. Workers always process blue-chip, high-ranking domains before touching low-quality pages.
    
-   **Tiered Waterfall Scraping:** * **Tier 1 (Fast Fetch):** Highly concurrent `httpx` requests to pull standard DOM data instantly.
    
    -   **Tier 2 (Stealth Fallback):** If Tier 1 encounters anti-bot protections, 403 Forbidden errors, or heavy JS-challenges, the Orchestrator autonomously boots a headless `Playwright` Chromium browser to intercept routes, render the JS, and safely bypass the shield.
        
-   **The Gigabrain Parser:** Utilizes custom Regex, BeautifulSoup, and JSON-LD schema parsing to extract emails and E.164 compliant phone numbers. Features built-in obfuscated email decryption (XOR bypass) and aggressive dummy-data filtering.
    

## 🚀 Execution Flow

1.  **Initialization:** The Orchestrator accepts a natural language prompt via the CLI, calculates the target deficit, and queries the LLM for a search strategy.
    
2.  **Harvesting:** `asyncio.to_thread` is used to launch background DuckDuckGo scraping, gathering hundreds of URLs without blocking the main event loop.
    
3.  **Queue Injection:** Domains are aggressively deduplicated and pushed into the Priority Queue.
    
4.  **Concurrency:** A predefined limit of asynchronous workers (e.g., 10-20) pluck URLs from the queue, execute the Waterfall Scraping protocol, and parse the data.
    
5.  **Graceful Shutdown:** The moment the exact target count is reached, a global kill switch is flipped, active headless browsers are safely terminated, and data is exported to a clean CSV.
    

## 🛠️ Tech Stack

-   **Language:** Python 3.10+
    
-   **Concurrency:** `asyncio`, `aiofiles`
    
-   **Scraping:** `httpx`, `playwright`, `beautifulsoup4`, `ddgs (duckduckgo-search)`
    
-   **Data Validation:** `pydantic`
    
-   **LLM Integration:** OpenRouter API (Compatible with Llama 3, Claude, GPT-4, etc.)
    

## ⚙️ Setup & Installation

1.  Clone the repository:
    

```
git clone [https://github.com/ehsaan700/autonomous-lead-gen-agent.git](https://github.com/ehsaan700/autonomous-lead-gen-agent.git)
cd autonomous-lead-gen-agent

```

2.  Install dependencies:
    

```
pip install -r requirements.txt
playwright install chromium

```

3.  Configure your Environment Variables: Create a `.env` file in the root directory:
    

```
OPENROUTER_API_KEY=your_api_key_here
MAX_CONCURRENT_WORKERS=10
MAX_PARALLEL_SEARCHES=3

```

4.  Run the Agent: Provide your natural language command directly in the terminal:
    

```
python main.py "Find me 50 PR agencies in Dallas, Texas."

```