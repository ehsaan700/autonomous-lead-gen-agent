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

logging.getLogger("asyncio").setLevel(logging.CRITICAL)

# 🟢 IMPORT FIX: Brought in the verification gates and scorers for Tier 2 to use
from extractor import extract_domain_tier1, extract_lead_data, verify_entity_gate, calculate_probabilistic_score
from schemas import EnrichedLead
from pydantic import ValidationError
from playwright_fallback import fetch_html_deep
from get_links import fetch_urls, get_unique_filename

load_dotenv()

MAX_CONCURRENT_WORKERS = int(os.getenv("MAX_CONCURRENT_WORKERS", 10)) 
MAX_PARALLEL_SEARCHES = int(os.getenv("MAX_PARALLEL_SEARCHES", 3))
MAX_SEARCH_ITERATIONS = 4  

@dataclass
class AgentState:
    ledger_filename: str
    user_prompt: str 
    target_lead_count: int
    topical_keywords: list = field(default_factory=list)
    url_queue: asyncio.PriorityQueue = field(default_factory=asyncio.PriorityQueue)
    seen_domains: set = field(default_factory=set)
    valid_leads: list = field(default_factory=list)
    kill_switch: asyncio.Event = field(default_factory=asyncio.Event)
    injection_counter: int = 0
    rejection_stats: dict = field(default_factory=dict)
    score_histogram: dict = field(default_factory=lambda: {90: 0, 80: 0, 70: 0, 60: 0, 50: 0, "Below 50": 0})

def log_score_to_histogram(state: AgentState, score: float):
    if score >= 90: state.score_histogram[90] += 1
    elif score >= 80: state.score_histogram[80] += 1
    elif score >= 70: state.score_histogram[70] += 1
    elif score >= 60: state.score_histogram[60] += 1
    elif score >= 50: state.score_histogram[50] += 1
    else: state.score_histogram["Below 50"] += 1

async def extractor_worker(worker_id: int, state: AgentState):
    try:
        while not state.kill_switch.is_set():
            try:
                rank, index, url = await asyncio.wait_for(state.url_queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue 
                
            try:
                if state.kill_switch.is_set():
                    break

                raw_data = await extract_domain_tier1(url, state.user_prompt, state.topical_keywords)
                score = raw_data.get("qualification_score", 0.0)

                # 🛑 THE TIER 2 GHOSTING FIX
                # If Tier 1 failed (Cloudflare 403), it returns a 0.0 score. 
                # We boot Playwright, but now we strictly score the resulting HTML!
                if score == 0.0 and not raw_data.get("email"):
                    html = await fetch_html_deep(url)
                    if html:
                        # 1. Gatekeeper checks the Playwright DOM
                        is_verified, gate_reason = verify_entity_gate(html, url, state.user_prompt, state.topical_keywords)
                        if not is_verified:
                            raise ValueError(f"Rejected: {gate_reason} (Score: 0.0)")
                        
                        # 2. Scorer runs on the Playwright DOM
                        lead_score, rejection_reason, score_breakdown = calculate_probabilistic_score(html, url, state.user_prompt, state.topical_keywords)
                        if lead_score < 40.0:
                            raise ValueError(f"Rejected: {rejection_reason} (Score: {lead_score:.1f})")
                        
                        # 3. Parsers grab the contact info
                        fallback_data = extract_lead_data(html, url)
                        raw_data["email"] = fallback_data["email"]
                        raw_data["phone_number"] = fallback_data["phone_number"]
                        raw_data["email_step"] = f"{fallback_data.get('email_step', 'Failed')} (Tier 2)"
                        raw_data["phone_step"] = f"{fallback_data.get('phone_step', 'Failed')} (Tier 2)"
                        
                        # 4. Save the new, valid score
                        score = lead_score
                        raw_data["qualification_score"] = score
                        raw_data["score_breakdown"] = score_breakdown
                    else:
                        raise ValueError("Rejected: Site Unreachable / Blocked (Score: 0.0)")

                # Now correctly log the score to the histogram AFTER Tier 2 runs
                log_score_to_histogram(state, score)
                        
                valid_lead = EnrichedLead(**raw_data)
                
                lead_dict = valid_lead.model_dump()
                lead_dict['qualification_score'] = score
                lead_dict['score_breakdown'] = raw_data.get('score_breakdown', {})
                
                state.valid_leads.append((rank, index, lead_dict))
                
                domain = urllib.parse.urlparse(url).netloc.replace('www.', '')
                print(f"  [+] Scored & Queued: {domain} (Score: {score:.1f})")
                        
            except ValidationError:
                pass 
            except ValueError as e:
                err_msg = str(e)
                if "Rejected:" in err_msg:
                    try:
                        score_str = err_msg.split("(Score: ")[1].replace(")", "").strip()
                        log_score_to_histogram(state, float(score_str))
                    except:
                        pass
                    
                    reason = err_msg.split("Rejected: ")[1].split(" (Score:")[0].strip()
                    state.rejection_stats[reason] = state.rejection_stats.get(reason, 0) + 1
            except Exception:
                pass
            finally:
                state.url_queue.task_done()
    except asyncio.CancelledError:
        pass

async def run_parallel_harvesters(queries: list[str]) -> list[tuple[int, str]]:
    print(f"🕸️  [Agent] Executing discovery web searches across {len(queries)} vectors...")
    tasks = [fetch_urls(query, max_results=30) for query in queries]
    results_matrix = await asyncio.gather(*tasks, return_exceptions=True)
    
    master_url_list = []
    for result in results_matrix:
        if isinstance(result, list): 
            for rank, url in enumerate(result):
                master_url_list.append((rank, url))
            
    return master_url_list

async def inject_new_urls(raw_urls: list[tuple[int, str]], state: AgentState, forbidden_tlds: tuple[str, ...]):
    new_count = 0
    async with aiofiles.open(state.ledger_filename, mode='a', encoding='utf-8') as ledger:
        for rank, url in raw_urls:
            if url.lower().endswith(('.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx')):
                continue

            domain = urllib.parse.urlparse(url).netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]
                
            if forbidden_tlds and domain.endswith(forbidden_tlds):
                continue
                
            if domain and domain not in state.seen_domains:
                state.seen_domains.add(domain)
                await state.url_queue.put((rank, state.injection_counter, url))
                await ledger.write(url + '\n')
                state.injection_counter += 1
                new_count += 1
                
    print(f"📥 [Agent] Ingested {new_count} unique real-world domains into the priority queue.")

async def ask_llm_for_strategy(user_prompt: str, state: AgentState, iteration: int) -> tuple[list[str], tuple[str, ...], list[str]]:
    prompt_context = f"User Request: {user_prompt}. This is iteration {iteration} of {MAX_SEARCH_ITERATIONS}. Generate unique search queries to find the target domains."
    print(f"\n🧠 [Agent] Formulating Discovery strategy (Iteration {iteration}/{MAX_SEARCH_ITERATIONS})...")

    messages = [
        {
            "role": "system",
            "content": (
                "You are an autonomous B2B lead generation architect. Your goal is to surface REAL company websites from the search engine.\n\n"
                "CRITICAL PARADIGM SHIFT (REAL-WORLD DISCOVERY):\n"
                "Do NOT invent or hallucinate company names. You are no longer generating entity names. Instead, you must generate HIGHLY SPECIFIC COMMERCIAL FOOTPRINTS designed to force the search engine to return real, existing businesses in its results.\n\n"
                "QUERY TEMPLATES:\n"
                "1. \"[Specific Service]\" \"consulting\" OR \"services\" [Target City/State]\n"
                "2. \"[Specific Service]\" \"contact us\" OR \"request a quote\" [Target City/State]\n"
                "Example 1: \"ISO 9001\" \"consulting services\" Atlanta GA\n"
                "Example 2: \"ISO implementation\" \"contact us\" Georgia\n\n"
                "CRITICAL SEARCH ENGINE RULES:\n"
                "1. NO BROAD QUERIES: Always anchor your queries with exact match commercial intent quotes (e.g. \"contact us\", \"our services\", \"consulting\").\n"
                "2. THE OFFSHORE .COM SHIELD: If targeting US/UK/EU, append negative keywords (e.g. -india -pakistan).\n\n"
                "REQUIRED JSON SCHEMA:\n"
                "{\n"
                "  \"target_count\": <int>,\n"
                "  \"forbidden_tlds\": [\"<list of string TLDs starting with a dot, e.g. '.in'>\"],\n"
                "  \"topical_keywords\": [\"<list of 10-15 highly specific industry keywords/services based on the user's request>\"],\n"
                f"  \"queries\": [\"<list of {MAX_PARALLEL_SEARCHES} strict DuckDuckGo footprint queries>\"]\n"
                "}\n"
                "Output RAW JSON ONLY. No markdown blocks."
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
            return [], (), []

        llm_payload = json.loads(response_data['choices'][0]['message']['content'])
            
        queries = llm_payload.get('queries', [])[:MAX_PARALLEL_SEARCHES]
        forbidden_tlds = tuple(tld.lower() for tld in llm_payload.get('forbidden_tlds', []))
        topical_keywords = [kw.lower() for kw in llm_payload.get('topical_keywords', [])]
        
        if state.target_lead_count == 0:
            state.target_lead_count = llm_payload.get('target_count', 50)
        
        if forbidden_tlds:
            print(f"🛡️  [Agent] Dynamic Firewall activated. Blocking TLDs: {', '.join(forbidden_tlds)}")
            
        return queries, forbidden_tlds, topical_keywords
        
    except Exception:
        print(f"⚠️ [Agent] Failed to parse LLM response due to server load. Retrying...")
        return [], (), []

async def main(user_prompt: str):
    safe_ledger_name = get_unique_filename("target_urls.txt")
    state = AgentState(ledger_filename=safe_ledger_name, user_prompt=user_prompt, target_lead_count=0)
    
    print(f"=== AUTONOMOUS LEAD GENERATION AGENT ===")
    print(f"Instruction: \"{user_prompt}\"")
    
    workers = [
        asyncio.create_task(extractor_worker(i, state)) 
        for i in range(MAX_CONCURRENT_WORKERS)
    ]
    
    iteration = 0
    while not state.kill_switch.is_set() and iteration < MAX_SEARCH_ITERATIONS:
        iteration += 1
        
        queries, forbidden_tlds, topical_keywords = await ask_llm_for_strategy(user_prompt, state, iteration)
        if not queries:
            await asyncio.sleep(2)
            continue
            
        state.topical_keywords = topical_keywords
            
        raw_urls = await run_parallel_harvesters(queries) 
        await inject_new_urls(raw_urls, state, forbidden_tlds)
        
        print("🕵️‍♂️ [Agent] Deep extraction protocol engaged. Scoring candidates...")
        kill_task = asyncio.create_task(state.kill_switch.wait())
        queue_task = asyncio.create_task(state.url_queue.join())
        
        done, pending = await asyncio.wait(
            [kill_task, queue_task], 
            return_when=asyncio.FIRST_COMPLETED
        )
        
        for task in pending:
            task.cancel()

    print("🧹 [Agent] Finalizing data assembly...")
    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    
    await asyncio.sleep(0.5)
        
    state.valid_leads.sort(key=lambda x: x[2].get('qualification_score', 0), reverse=True)
    
    accepted_leads = []
    rejected_leads = []
    
    for rank, index, lead in state.valid_leads:
        # 🟢 THE OVERFLOW FIX: Removed the artificial quota cap.
        # If 48 companies score over a 60.0, the user gets all 48.
        if lead.get('qualification_score', 0) >= 60.0:
            accepted_leads.append(lead)
        else:
            rejected_leads.append(lead)
    
    print("\n📊 [Agent] Pipeline Qualification Analytics:")
    print(f"   - Discovered & Evaluated: {state.injection_counter} domains")
    print(f"   - Qualified > 90 score: {state.score_histogram[90]}")
    print(f"   - Qualified > 80 score: {state.score_histogram[80]}")
    print(f"   - Qualified > 70 score: {state.score_histogram[70]}")
    print(f"   - Qualified > 60 score: {state.score_histogram[60]}")
    print(f"   - Qualified > 50 score: {state.score_histogram[50]}")
    print(f"   - Rejected < 50 score: {state.score_histogram['Below 50']}\n")

    print("❌ Top Rejected Domains (Near Misses):")
    for lead in rejected_leads[:5]:
        domain = urllib.parse.urlparse(str(lead['source_url'])).netloc.replace('www.', '')
        b = lead.get('score_breakdown', {})
        print(f"   - {domain} | Score: {lead.get('qualification_score', 0):.1f} | H:{b.get('H',0):.2f} I:{b.get('I',0):.2f} C:{b.get('C',0):.2f} D:{b.get('D',0):.2f}")
    
    if accepted_leads:
        csv_filename = get_unique_filename("extracted_leads.csv")
        keys = accepted_leads[0].keys()
        
        cleaned_leads = []
        for lead in accepted_leads:
            lead_copy = dict(lead)
            lead_copy.pop('qualification_score', None)
            lead_copy.pop('score_breakdown', None)
            
            lead_copy['source_url'] = str(lead_copy['source_url'])
            
            cleaned_leads.append(lead_copy)

        with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
            dict_writer = csv.DictWriter(f, fieldnames=[k for k in keys if k not in ['qualification_score', 'score_breakdown']])
            dict_writer.writeheader()
            dict_writer.writerows(cleaned_leads)
        print(f"\n✨ [SUCCESS] Precision protocol complete. {len(accepted_leads)} highly qualified leads saved to {csv_filename}!")
    else:
        print("\n⚠️ [WARNING] Exhausted all search limits. No leads found matching the quality threshold.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous B2B Lead Generation Agent")
    parser.add_argument(
        "prompt", 
        type=str, 
        help="The natural language instruction for the agent (e.g., 'Find me 50 PR agencies in Dallas')"
    )
    
    args = parser.parse_args()
    asyncio.run(main(args.prompt))