import asyncio
import os
import aiofiles
import httpx
import json
import csv
import urllib.parse
import argparse
import logging 
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Import your native components
from extractor import extract_domain_tier1
from schemas import EnrichedLead
from pydantic import ValidationError
from playwright_fallback import fetch_html_deep
from get_links import fetch_urls, get_unique_filename

load_dotenv()

logging.getLogger("asyncio").setLevel(logging.CRITICAL)
MAX_CONCURRENT_WORKERS = int(os.getenv("MAX_CONCURRENT_WORKERS", 10)) 
MAX_PARALLEL_SEARCHES = int(os.getenv("MAX_PARALLEL_SEARCHES", 3))

@dataclass
class AgentState:
    target_lead_count: int
    ledger_filename: str
    url_queue: asyncio.PriorityQueue = field(default_factory=asyncio.PriorityQueue)
    seen_domains: set = field(default_factory=set)
    valid_leads: list = field(default_factory=list)
    kill_switch: asyncio.Event = field(default_factory=asyncio.Event)
    injection_counter: int = 0

async def extractor_worker(worker_id: int, state: AgentState):
    # Silenced the noisy "Worker Booted" prints
    try:
        while not state.kill_switch.is_set():
            try:
                rank, index, url = await asyncio.wait_for(state.url_queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue 
                
            try:
                if state.kill_switch.is_set():
                    break

                raw_data = await extract_domain_tier1(url)

                if not raw_data.get("email") and not raw_data.get("phone_number"):
                    # Silenced the "Triggering Playwright" print. The Agent does this silently now.
                    html = await fetch_html_deep(url)
                    if html:
                        # Late import to avoid circular dependencies if any exist
                        from extractor import extract_lead_data
                        raw_data = extract_lead_data(html, url)
                        raw_data["email_step"] = f"{raw_data.get('email_step', 'Failed')} (Tier 2)"
                        raw_data["phone_step"] = f"{raw_data.get('phone_step', 'Failed')} (Tier 2)"
                        
                valid_lead = EnrichedLead(**raw_data)
                
                state.valid_leads.append((rank, index, valid_lead.model_dump()))
                
                # Elegant, abstracted success message
                domain = urllib.parse.urlparse(url).netloc.replace('www.', '')
                print(f"  [+] Lead Acquired: {domain} ({len(state.valid_leads)}/{state.target_lead_count})")
                
                if len(state.valid_leads) >= state.target_lead_count and not state.kill_switch.is_set():
                    print("\n🎯 [Agent] Target objective reached. Initiating clean shutdown.")
                    state.kill_switch.set()
                        
            except ValidationError:
                # Silently drop invalid leads
                pass 
            except Exception:
                # Silently drop failed URLs instead of spamming the console
                pass
            finally:
                state.url_queue.task_done()
    except asyncio.CancelledError:
        pass

async def run_parallel_harvesters(queries: list[str]) -> list[tuple[int, str]]:
    print(f"🕸️  [Agent] Executing distributed web searches across {len(queries)} vectors...")
    tasks = [fetch_urls(query, max_results=50) for query in queries]
    results_matrix = await asyncio.gather(*tasks, return_exceptions=True)
    
    master_url_list = []
    for result in results_matrix:
        if isinstance(result, list): 
            for rank, url in enumerate(result):
                master_url_list.append((rank, url))
            
    return master_url_list

async def inject_new_urls(raw_urls: list[tuple[int, str]], state: AgentState):
    new_count = 0
    async with aiofiles.open(state.ledger_filename, mode='a', encoding='utf-8') as ledger:
        for rank, url in raw_urls:
            if url.lower().endswith(('.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx')):
                continue

            domain = urllib.parse.urlparse(url).netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
                
            if domain and domain not in state.seen_domains:
                state.seen_domains.add(domain)
                await state.url_queue.put((rank, state.injection_counter, url))
                await ledger.write(url + '\n')
                state.injection_counter += 1
                new_count += 1
                
    print(f"📥 [Agent] Ingested {new_count} unique domains into the priority queue.")

async def ask_llm_for_strategy(user_prompt: str, state: AgentState) -> list[str]:
    current_leads = len(state.valid_leads)
    
    if state.target_lead_count == 0:
        prompt_context = f"User Request: {user_prompt}. This is the first run. Extract the target number of leads requested and generate initial queries."
        print(f"\n🧠 [Agent] Analyzing request and formulating initial search strategy...")
    else:
        deficit = state.target_lead_count - current_leads
        target_urls_needed = max(10, deficit * 2) 
        prompt_context = f"User Request: {user_prompt}. We have {current_leads} leads and need {deficit} more. Give me queries to find ~{target_urls_needed} domains."
        print(f"\n🧠 [Agent] Deficit identified ({deficit} leads). Recalibrating search strategy...")

    messages = [
        {
            "role": "system",
            "content": (
                "You are an autonomous lead generation strategist. "
                "Return a JSON object with exactly two keys: "
                f"'target_count' (int) and 'queries' (list of {MAX_PARALLEL_SEARCHES} highly varied DuckDuckGo search strings to find B2B domains). "
                "Output RAW JSON ONLY."
            )
        },
        {
            "role": "user",
            "content": prompt_context
        }
    ]

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-oss-120b:free", 
                "messages": messages,
                "response_format": {"type": "json_object"} 
            },
            timeout=15.0
        )
        
    try:
        response_data = response.json()
        
        if 'error' in response_data:
            print(f"🛑 [API Error]: Upstream LLM provider is congested. Retrying...")
            return []

        llm_payload = json.loads(response_data['choices'][0]['message']['content'])
        
        if state.target_lead_count == 0:
            parsed_target = llm_payload.get('target_count', 50)
            state.target_lead_count = parsed_target if parsed_target > 0 else 50
            print(f"🎯 [Agent] Target objective locked at {state.target_lead_count} leads.")
            
        return llm_payload.get('queries', [])[:MAX_PARALLEL_SEARCHES]
        
    except Exception:
        print(f"⚠️ [Agent] Failed to parse LLM response due to server load. Retrying...")
        return []

async def main(user_prompt: str):
    # --- NEW: Silence Playwright's background shutdown ghosts ---
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda l, context: None if "TargetClosedError" in str(context.get('exception', '')) else l.default_exception_handler(context))
    
    safe_ledger_name = get_unique_filename("target_urls.txt")
    state = AgentState(target_lead_count=0, ledger_filename=safe_ledger_name)
    
    print(f"=== AUTONOMOUS LEAD GENERATION AGENT ===")
    print(f"Instruction: \"{user_prompt}\"")
    
    workers = [
        asyncio.create_task(extractor_worker(i, state)) 
        for i in range(MAX_CONCURRENT_WORKERS)
    ]
    
    max_iterations = 10 
    iteration = 0
    
    while not state.kill_switch.is_set() and iteration < max_iterations:
        iteration += 1
        
        # 1. OpenRouter formulates strategy
        queries = await ask_llm_for_strategy(user_prompt, state)
        if not queries:
            await asyncio.sleep(2)
            continue
            
        # 2. Harvester pulls raw URLs
        raw_urls = await run_parallel_harvesters(queries) 
        
        # 3. Inject deduplicated URLs into Queue
        await inject_new_urls(raw_urls, state)
        
        # 4. Wait for the workers
        print("🕵️‍♂️ [Agent] Deep extraction protocol engaged. Bypassing anti-bot shields silently...")
        kill_task = asyncio.create_task(state.kill_switch.wait())
        queue_task = asyncio.create_task(state.url_queue.join())
        
        done, pending = await asyncio.wait(
            [kill_task, queue_task], 
            return_when=asyncio.FIRST_COMPLETED
        )
        
        for task in pending:
            task.cancel()
            
        if state.kill_switch.is_set():
            break

    print("🧹 [Agent] Finalizing data assembly...")
    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
        
    state.valid_leads.sort(key=lambda x: (x[0], x[1]))
    final_ordered_leads = [lead for rank, index, lead in state.valid_leads][:state.target_lead_count]
    
    if final_ordered_leads:
        csv_filename = get_unique_filename("extracted_leads.csv")
        keys = final_ordered_leads[0].keys()
        with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
            dict_writer = csv.DictWriter(f, fieldnames=keys)
            dict_writer.writeheader()
            dict_writer.writerows(final_ordered_leads)
        print(f"\n✨ [SUCCESS] Captured {len(final_ordered_leads)} leads and saved to {csv_filename}!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous B2B Lead Generation Agent")
    parser.add_argument(
        "prompt", 
        type=str, 
        help="The natural language instruction for the agent (e.g., 'Find me 50 PR agencies in Dallas')"
    )
    
    args = parser.parse_args()
    asyncio.run(main(args.prompt))