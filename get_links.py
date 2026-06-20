import urllib.parse
import sys
import os
import asyncio

# 1. Graceful Import Handling
try:
    from ddgs import DDGS
except ImportError:
    #print("CRITICAL: duckduckgo_search is missing. Run: pip install duckduckgo-search")
    sys.exit(1)

# The core exclusion list
EXCLUDED_KEYWORDS = [
    "facebook", "instagram", "linkedin", "telegram", "t.me", 
    "whatsapp", "tiktok", "yelp", "clutch", "reddit", "twitter", "x.com",
    "upcity", "sortlist", "themanifest", "designrush", "g2", "goodfirms",
    "expertise", "crunchbase", "glassdoor", "ziprecruiter", "indeed",
    "50pros", "semfirms", "kokoquest", "directory", "bizjournals", 
    "google", "youtube"
]

def get_unique_filename(filepath: str) -> str:
    if not os.path.exists(filepath):
        return filepath
    base, ext = os.path.splitext(filepath)
    counter = 1
    while True:
        new_filepath = f"{base} ({counter}){ext}"
        if not os.path.exists(new_filepath):
            return new_filepath
        counter += 1

# ==========================================
# PHASE 4 ASYNC INTEGRATION
# ==========================================
def _blocking_fetch(search_query: str, max_results: int) -> list[str]:
    """Underlying blocking function that actually runs DDGS."""
    results = DDGS().text(search_query, max_results=max_results)
    valid_urls = []
    
    if not results:
        return valid_urls
        
    for item in results:
        url = item.get("href", "")
        if not url:
            continue
            
        domain = urllib.parse.urlparse(url).netloc.lower()
        is_excluded = any(bad_word in domain for bad_word in EXCLUDED_KEYWORDS)
        
        if not is_excluded:
            valid_urls.append(url)
            
    return valid_urls

async def fetch_urls(search_query: str, max_results: int = 50) -> list[str]:
    """
    Phase 4 hook: Runs the blocking DDGS search in a background thread 
    so it doesn't freeze our massive async worker fleet. Returns raw URLs.
    """
    #print(f"[*] Fetching URLs for: '{search_query}'")
    try:
        # asyncio.to_thread pushes the blocking network call to a background thread
        return await asyncio.to_thread(_blocking_fetch, search_query, max_results)
    except Exception as e:
        #print(f"⚠️ Search failed for '{search_query}': {e}")
        return []

# ==========================================
# PHASE 1 LEGACY (Standalone)
# ==========================================
def tool_harvester(search_query: str, max_results: int = 50, output_filepath: str = "target_urls.txt") -> str:
    """Legacy function for standalone execution."""
    #print(f"[*] Running Harvester Tool for query: '{search_query}'")
    
    try:
        valid_urls = _blocking_fetch(search_query, max_results)
    except Exception as e:
        return f"Search execution failed due to network/API error: {str(e)}"
    
    if not valid_urls:
        return "Search returned 0 valid results. Agent should try a different query."

    safe_output_filepath = get_unique_filename(output_filepath)
    try:
        with open(safe_output_filepath, "w", encoding="utf-8") as file:
            for valid_url in valid_urls:
                file.write(valid_url + "\n")
    except Exception as e:
        return f"Failed to save data due to a file system error: {str(e)}"

    return f"Success. Extracted and saved {len(valid_urls)} valid URLs to {safe_output_filepath}."

if __name__ == "__main__":
    if len(sys.argv) < 2:
        #print("Error: Missing search query. Usage: python get_links.py 'search query' [max_results]")
        sys.exit(1)
        
    query = sys.argv[1]
    max_results = int(sys.argv[2]) if len(sys.argv) >= 3 else 50
    #print(tool_harvester(query, max_results))