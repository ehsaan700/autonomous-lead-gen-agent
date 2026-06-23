import urllib.parse
import sys
import os
import asyncio

try:
    from ddgs import DDGS
except ImportError:
    print("CRITICAL: duckduckgo_search is missing. Run: pip install duckduckgo-search")
    sys.exit(1)

EXCLUDED_KEYWORDS = [
    "facebook", "instagram", "linkedin", "telegram", "t.me", 
    "whatsapp", "tiktok", "yelp", "clutch", "reddit", "twitter", "x.com",
    "upcity", "sortlist", "themanifest", "designrush", "g2", "goodfirms",
    "expertise", "crunchbase", "glassdoor", "ziprecruiter", "indeed",
    "50pros", "semfirms", "kokoquest", "directory", "bizjournals", 
    "google", "youtube", "zoominfo", "yellowpages", "quora", "medium", 
    "blogspot", "wordpress", "coursera", "udemy", "skillshare", 
    "tripadvisor", "foursquare", "trustpilot", "capterra", "g2crowd",
    "einnews", "fortunebusinessinsights", "prnewswire", "globenewswire", 
    "businesswire", "bloomberg", "forbes", "researchandmarkets"
]

# 🛑 MASSIVELY EXPANDED B2C & MEDIA PATH BLOCKER
EXCLUDED_PATHS = [
    "/blog", "/blogs", "/post", "/posts", "/article", "/articles", 
    "/news", "/resources", "/guide", "/guides", "/training", "/course", 
    "/courses", "/webinar", "/events", "/academy", "/knowledge-base", 
    "/faq", "/docs", "/listicle", "/top-10", "/best-", "/directory", 
    "/companies", "/suppliers", "/listings", "/insights", "/reports", "/press-release",
    "/forum", "/thread", "/podcast", "/jobs", "/careers", "/resume", "/marketplace", "/listing"
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

def score_url_priority(url: str) -> int:
    url_lower = url.lower()
    parsed = urllib.parse.urlparse(url_lower)
    path = parsed.path
    score = 0
    
    if path in ["", "/"]:
        score -= 10
    elif "contact" in path or "about" in path:
        score -= 5
        
    directories = ["yelp", "clutch", "zoominfo", "yellowpages", "crunchbase", "bbb.org", "mapquest", "capterra"]
    if any(d in parsed.netloc for d in directories):
        score += 50
        
    return score

def _blocking_fetch(search_query: str, max_results: int) -> list[str]:
    results = DDGS().text(search_query, max_results=max_results)
    valid_urls = []
    
    if not results:
        return valid_urls
        
    for item in results:
        url = item.get("href", "")
        if not url or url.lower().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
            continue
            
        url_lower = url.lower()
        domain = urllib.parse.urlparse(url_lower).netloc
        
        is_excluded_domain = any(bad_word in domain for bad_word in EXCLUDED_KEYWORDS)
        is_informational_path = any(bad_path in url_lower for bad_path in EXCLUDED_PATHS)
        is_invalid_tld = domain.endswith((".gov", ".edu"))
        
        if not is_excluded_domain and not is_informational_path and not is_invalid_tld:
            valid_urls.append(url)
            
    valid_urls.sort(key=score_url_priority)
    return valid_urls

async def fetch_urls(search_query: str, max_results: int = 50) -> list[str]:
    print(f"[*] Fetching URLs for: '{search_query}'")
    try:
        return await asyncio.to_thread(_blocking_fetch, search_query, max_results)
    except Exception as e:
        print(f"⚠️ Search failed for '{search_query}': {e}")
        return []

def tool_harvester(search_query: str, max_results: int = 50, output_filepath: str = "target_urls.txt") -> str:
    print(f"[*] Running Harvester Tool for query: '{search_query}'")
    try:
        valid_urls = _blocking_fetch(search_query, max_results)
    except Exception as e:
        return f"Search execution failed due to network/API error: {str(e)}"
    
    if not valid_urls:
        return "Search returned 0 valid results."

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
        print("Error: Missing search query. Usage: python get_links.py 'search query' [max_results]")
        sys.exit(1)
        
    query = sys.argv[1]
    max_results = int(sys.argv[2]) if len(sys.argv) >= 3 else 50
    print(tool_harvester(query, max_results))