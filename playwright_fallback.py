import asyncio
import csv
from playwright.async_api import async_playwright
import os

# The Handoff: We import your 6-step parser from the other file!
from extractor import extract_lead_data 

async def fetch_html_deep(url: str) -> str | None:
    """
    Tier 2 Playwright Engine: Renders JS, blocks media, returns raw HTML.
    """
    #print(f"  [Playwright] Booting stealth browser for {url}...")
    try:
        async with async_playwright() as p:
            # PHASE 1: Boot-Up
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            # PHASE 2: Interception (Speed Optimization)
            # We block anything that isn't essential HTML/JS
            async def route_intercept(route):
                try:
                    if route.request.resource_type in ["image", "stylesheet", "media", "font"]:
                        await route.abort()
                    else:
                        await route.continue_()
                except Exception:
                    pass
            
            await page.route("**/*", route_intercept)

            # 🚀 PHASE 3: Navigation (Optimized)
            # Wait for 'load' (scripts downloaded) instead of 'networkidle' (which hangs)
            await page.goto(url, wait_until="load", timeout=15000)
            
            # Explicitly wait 1.5 seconds for React/Vue SPA DOM hydration
            await page.wait_for_timeout(1500)
            
            # PHASE 4: Extraction
            html = await page.content()
            # 🟢 NEW: Clear success indicator before closing the browser
            #print(f"  [Playwright] 🟢 Successfully breached and rendered: {url}")
            
            # PHASE 5: Teardown
            await browser.close()
            return html
            
    except asyncio.CancelledError:
        # Handles the Orchestrator's violent kill_switch shutdown cleanly
        return None
    
    except Exception as e:
        # Suppress the messy TargetClosedError traceback 
        #if "TargetClosedError" not in str(type(e)):
            #print(f"  [Playwright Failed] {url} - {str(e)}")
        return None

async def main():
    target_file = "target_urls.txt"
    
    # 1. Check if the file exists
    if not os.path.exists(target_file):
        #print(f"Error: {target_file} not found. Please create it and add some URLs.")
        return

    # 2. Read the file line by line
    with open(target_file, "r") as f:
        test_urls = [line.strip() for line in f if line.strip()]

    # 3. Check if the file is empty
    if not test_urls:
        #print(f"Error: {target_file} is empty.")
        return

    #print(f"Loaded {len(test_urls)} URLs from {target_file}.")
    
    valid_leads = []

    for url in test_urls:
        #print(f"\nTarget: {url}")
        html = await fetch_html_deep(url)
        
        if html:
            # PHASE 6: The Handoff
            #print(f"  [Parser] Handoff complete. Running 6-step protocol...")
            data = extract_lead_data(html, url)
            
            # Filter out failures before writing to CSV
            if data["extraction_step"] != "Failed":
                #print(f"  [SUCCESS] Found contact via {data['extraction_step']}")
                valid_leads.append(data)
            #else:
                #print("  [FAILED] No contact info found.")

    # ---------------------------------------------------------
    # CSV EXPORT
    # ---------------------------------------------------------
    if valid_leads:
        csv_filename = "playwright_leads.csv"
        with open(csv_filename, "w", newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=valid_leads[0].keys())
            writer.writeheader()
            for lead in valid_leads:
                writer.writerow(lead)
        #print(f"\n[DONE] Saved {len(valid_leads)} leads to {csv_filename}")
    #else:
        #print("\n[DONE] No valid leads to save.")

if __name__ == "__main__":
    # Ensure browsers are installed via terminal: playwright install
    asyncio.run(main())