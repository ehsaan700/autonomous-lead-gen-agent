import httpx
import asyncio
import re
import json
import urllib.parse
from bs4 import BeautifulSoup

# ==========================================
# STAGE 1: THE ENTITY TRUTH FILTER (GATE)
# ==========================================
def verify_entity_gate(html: str, url: str, user_prompt: str, topical_keywords: list) -> tuple[bool, str]:
    """
    Lightweight deterministic gate to verify we are looking at a real company 
    in the correct domain BEFORE we apply probabilistic ranking.
    """
    url_lower = url.lower()
    soup = BeautifulSoup(html, "html.parser")
    text_content = soup.get_text(separator=" ", strip=True).lower()
    
    # 1. The Structure Check: Is this an actual business website?
    # A real B2B company MUST have a commercial navigation footprint.
    business_nav = ["contact", "about", "services", "solutions", "our team", "request a quote", "pricing"]
    if not any(nav in text_content[:4000] or nav in url_lower for nav in business_nav):
        return False, "Gate Failed: No B2B Structural Footprint"
        
    # 2. The Platform/Noise Check: Catch escaped social media or directories
    platforms = ["linkedin.com", "facebook.com", "twitter.com", "zoominfo.com", "yelp.com", "yellowpages.com", "glassdoor.com", "indeed.com", "medium.com", "wikipedia.org"]
    if any(p in url_lower for p in platforms):
        return False, "Gate Failed: Social/Platform Profile"

    # 3. The Topical Grounding Check: Does it actually do the thing?
    # It must contain at least ONE core topical keyword identified by the LLM
    if topical_keywords:
        if not any(kw in text_content for kw in topical_keywords):
            return False, "Gate Failed: Zero Topical Grounding"
            
    # 4. The Geo/Intent Grounding Check: Is it remotely in the right place?
    prompt_lower = user_prompt.lower()
    stop_words = {'find', 'companies', 'state', 'city', 'with', 'that', 'have', 'need', 'some', 'good', 'best', 'please', 'the', 'in', 'of', 'for', 'and', 'to', 'a', 'an'}
    
    geo_intent_words = [w for w in re.findall(r'\b[a-z]{4,}\b', prompt_lower) if w not in stop_words and w not in topical_keywords]
    
    if geo_intent_words:
        us_synonyms = ["usa", "united states", "america", "national", "nationwide"]
        has_geo = any(g in text_content for g in geo_intent_words)
        has_us_override = any(s in prompt_lower for s in ["georgia", "texas", "california", "florida", "york"]) and any(us in text_content for us in us_synonyms)
        
        if not (has_geo or has_us_override):
            return False, "Gate Failed: Zero Geographic Grounding"
            
    return True, "Verified Entity"

# ==========================================
# STAGE 2: UNIVERSAL PROBABILISTIC RANKING
# ==========================================
def calculate_probabilistic_score(html: str, url: str, user_prompt: str, topical_keywords: list) -> tuple[float, str, dict]:
    """Calculates a weighted 4-axis probability score and returns the breakdown."""
    url_lower = url.lower()
    soup = BeautifulSoup(html, "html.parser")
    
    title = soup.title.string.lower() if soup.title and soup.title.string else ""
    text_content = soup.get_text(separator=" ", strip=True).lower()
    parsed_url = urllib.parse.urlparse(url_lower)
    path = parsed_url.path
    netloc = parsed_url.netloc.replace('www.', '')

    prompt_lower = user_prompt.lower()
    stop_words = {'find', 'companies', 'state', 'city', 'with', 'that', 'have', 'need', 'some', 'good', 'best', 'please', 'the', 'in', 'of', 'for', 'and', 'to', 'a', 'an'}

    # ---------------------------------------------------------
    # AXIS 1: HIREABILITY (H) - 0.0 to 1.0
    # ---------------------------------------------------------
    h_score = 0.1
    
    if any(kw in path for kw in ['service', 'solution', 'consult']): h_score += 0.2
    if any(kw in text_content[:5000] for kw in ['our services', 'what we do', 'capabilities']): h_score += 0.2
    if any(kw in text_content[:5000] for kw in ['consulting', 'firm', 'agency', 'provider', 'partner', 'specialists']): h_score += 0.2
    if any(kw in text_content[:5000] for kw in ['hire us', 'request a quote', 'book a consultation', 'get started']): h_score += 0.3
    
    H = min(1.0, h_score)

    # ---------------------------------------------------------
    # AXIS 2: INTENT ALIGNMENT (I) - 0.0 to 1.0
    # ---------------------------------------------------------
    if not topical_keywords:
        topical_keywords = [w for w in re.findall(r'\b[a-z]{4,}\b', prompt_lower) if w not in stop_words]
    
    t_hits = sum(1 for w in topical_keywords if w in text_content or w in title)
    topical_val = min(1.0, t_hits / 3.0) 

    prompt_words = set(re.findall(r'\b[a-z]{3,}\b', prompt_lower)) - stop_words
    geo_keywords = prompt_words - set(topical_keywords)
    
    if geo_keywords:
        geo_hits = sum(1 for w in geo_keywords if re.search(r'\b' + re.escape(w) + r'\b', text_content[:5000]))
        geo_val = min(1.0, geo_hits / 2.0)
    else:
        geo_val = 1.0 
        
    offshore_hubs = ["singapore", "qatar", "dubai", "india", "london", "uk", "australia", "pakistan", "bangladesh", "philippines", "ireland", "kuwait", "saudi arabia"]
    if not any(h in geo_keywords for h in offshore_hubs):
        foreign_hits = sum(1 for hub in offshore_hubs if re.search(r'\b' + hub + r'\b', text_content[:3000]))
        if foreign_hits > 0:
            geo_val -= 0.4 
            
    geo_val = max(0.0, geo_val)
    I = (topical_val * 0.7) + (geo_val * 0.3)

    # ---------------------------------------------------------
    # AXIS 3: ENTITY CLARITY (C) - 0.0 to 1.0
    # ---------------------------------------------------------
    C = 1.0
    
    dir_signals = ["directory", "listing", "yelp", "clutch", "zoominfo", "yellowpages", "glassdoor", "trustpilot", "allbiz"]
    if any(d in url_lower for d in dir_signals) or any(d in title for d in dir_signals): C -= 0.8
        
    job_signals = ["job board", "postjobfree", "indeed", "monster", "ziprecruiter", "vacancies"]
    if any(j in url_lower for j in job_signals) or any(j in title for j in job_signals): C -= 0.8
        
    media_signals = ["news", "magazine", "blog", "article", "journal", "wiki", "forum", "podcast"]
    if any(m in url_lower for m in media_signals) or any(m in title for m in media_signals): C -= 0.6
        
    b2c_signals = ["restaurant", "bbq", "menu", "hotel", "apartment", "real estate", "casino", "apparel", "cafe", "bakery", "movie theater", "law firm", "hospital", "church", "school", "flight"]
    if any(re.search(r'\b' + w + r'\b', title) for w in b2c_signals): C -= 0.8
        
    bad_subdomains = ["blog.", "news.", "support.", "docs.", "shop.", "store.", "restaurants.", "menu.", "order.", "careers.", "jobs."]
    if any(netloc.startswith(sub) for sub in bad_subdomains): C -= 0.5

    C = max(0.0, C)

    # ---------------------------------------------------------
    # AXIS 4: COMMERCIAL DEPTH (D) - 0.0 to 1.0
    # ---------------------------------------------------------
    depth_signals = ["pricing", "contact sales", "get a quote", "book demo", "case studies", "testimonials", "client success"]
    d_hits = sum(1 for w in depth_signals if w in text_content[:5000])
    D = min(1.0, d_hits / 3.0)

    # ==========================================
    # 🔥 THE NEW INTENT-HEAVY FORMULA 🔥
    # ==========================================
    final_score = (0.20 * H) + (0.55 * I) + (0.15 * C) + (0.10 * D)
    final_score_100 = final_score * 100.0
    
    score_breakdown = {"H": H, "I": I, "C": C, "D": D}

    rejection_reason = "Passed Qualification"
    if final_score_100 < 50.0:
        if C < 0.4:
            if any(d in url_lower for d in dir_signals): rejection_reason = "Entity: Directory/Aggregator"
            elif any(j in url_lower for j in job_signals): rejection_reason = "Entity: Job Board"
            elif any(re.search(r'\b' + w + r'\b', title) for w in b2c_signals): rejection_reason = "Entity: Irrelevant Industry (B2C)"
            else: rejection_reason = "Entity: Media/Blog/Informational"
        elif I < 0.4: rejection_reason = "Intent: Low Topical or Geo Alignment"
        elif H < 0.4: rejection_reason = "Hireability: Lacks B2B Service Footprint"
        else: rejection_reason = "Depth: Low Commercial Viability"

    return final_score_100, rejection_reason, score_breakdown

# ==========================================
# TIER 1: FAST FETCH (httpx)
# ==========================================
async def fetch_html_fast(url: str) -> str | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        async with httpx.AsyncClient(headers=headers, timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
    except Exception as e:
        if not url.rstrip('/').endswith(('contact', 'about', 'contact-us')):
            pass 
        return None

# ==========================================
# THE 6-STEP PARSER
# ==========================================
def extract_lead_data(html: str, source_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    text_content = soup.get_text(separator=" ", strip=True)
    
    lead_data = {
        "source_url": source_url,
        "email": None,
        "phone_number": None,
        "email_step": "Failed",
        "phone_step": "Failed"
    }

    email_regex = re.compile(r"([a-zA-Z0-9._%+-]+(?:@|\[at\])[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", re.IGNORECASE)
    phone_regex = re.compile(r"(?<!\d)(?:(?:\+?\d{1,3}[\s.-]{0,3})?\(?\d{3}\)?[\s.-]{0,3}\d{3}[\s.-]{0,3}\d{4})(?!\d)")
    
    def is_valid_email(email_str: str) -> bool:
        email_lower = email_str.lower()
        if "@" not in email_lower or "." not in email_lower.split("@")[-1]: return False
        invalid_extensions = ('.png', '.jpg', '.jpeg', '.svg', '.gif', '.js', '.css', 'w3.org')
        dummy_domains = ('example.com', 'domain.com', 'yoursite.com', 'email.com', 'sentry.io', 'yourcompany.com', 'company.com', 'mysite.com')
        if email_lower.endswith(invalid_extensions): return False
        if email_lower.startswith(('user@', 'name@', 'info@your', 'you@')): return False
        for dummy in dummy_domains:
            if dummy in email_lower: return False
        return True

    def is_valid_phone(phone_str: str, is_tel: bool = False) -> bool:
        clean_str = re.sub(r'\D', '', phone_str)
        if not (10 <= len(clean_str) <= 15): return False
        if not is_tel:
            if phone_str.strip() == clean_str and not phone_str.strip().startswith('+'): return False
            if re.search(r'\d{5,}[\s.-]+', phone_str) or re.search(r'[\s.-]+\d{5,}', phone_str): return False
            if re.search(r'[a-zA-Z]', phone_str): return False
            if phone_str.count(' ') > 2 and not any(c in phone_str for c in '+()-'): return False
        if re.search(r'(\d)\1{6,}', clean_str): return False
        if "123456789" in clean_str or "098765432" in clean_str: return False
        if clean_str.startswith("0000"): return False
        if clean_str.startswith("123456"): return False
        return True

    # STEP 1A: Mailto
    if not lead_data["email"]:
        for a_tag in soup.find_all('a', href=re.compile(r'(?i)^\s*mailto:')):
            raw_email = re.sub(r'(?i)^\s*mailto:\s*', '', a_tag['href']).split('?')[0].strip()
            raw_email = urllib.parse.unquote(raw_email)
            if is_valid_email(raw_email):
                lead_data["email"] = raw_email
                lead_data["email_step"] = "Step 1: Mailto"
                break

    # STEP 1B: Tel
    if not lead_data["phone_number"]:
        for a_tag in soup.find_all('a', href=re.compile(r'(?i)^\s*tel:')):
            raw_phone = re.sub(r'(?i)^\s*tel:\s*', '', a_tag['href']).split('?')[0].strip()
            raw_phone = urllib.parse.unquote(raw_phone)
            if is_valid_phone(raw_phone, is_tel=True):
                lead_data["phone_number"] = raw_phone
                lead_data["phone_step"] = "Step 1: Tel Anchor"
                break
                
    # STEP 1C: Cloudflare
    if not lead_data["email"]:
        for tag in soup.find_all(True):
            cf_data = tag.get('data-cfemail')
            if not cf_data and tag.name == 'a':
                href = tag.get('href', '')
                if '/cdn-cgi/l/email-protection#' in href:
                    cf_data = href.split('#')[-1]
            if cf_data:
                cf_data = cf_data.strip().split('?')[0]
                cf_data = re.sub(r'[^a-fA-F0-9]', '', cf_data)
                if len(cf_data) >= 4 and len(cf_data) % 2 == 0:
                    try:
                        key = int(cf_data[:2], 16)
                        decoded_email = "".join([chr(int(cf_data[i:i+2], 16) ^ key) for i in range(2, len(cf_data), 2)])
                        if is_valid_email(decoded_email):
                            lead_data["email"] = decoded_email
                            lead_data["email_step"] = "Step 1: CF Decode"
                            break
                    except Exception:
                        continue

    # STEP 2: JSON-LD
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            blocks = data if isinstance(data, list) else [data]
            for block in blocks:
                if isinstance(block, dict):
                    block_type = block.get('@type', '')
                    if block_type in ["LocalBusiness", "Organization", "ProfessionalService"]:
                        email_data = block.get('email')
                        phone_data = block.get('telephone')
                        if phone_data and not lead_data["phone_number"]:
                            if isinstance(phone_data, str) and is_valid_phone(phone_data):
                                lead_data["phone_number"] = phone_data
                                lead_data["phone_step"] = "Step 2: JSON-LD"
                            elif isinstance(phone_data, list) and len(phone_data) > 0 and is_valid_phone(str(phone_data[0])):
                                lead_data["phone_number"] = str(phone_data[0])
                                lead_data["phone_step"] = "Step 2: JSON-LD"
                        if email_data and not lead_data["email"]:
                            emails_to_check = [email_data] if isinstance(email_data, str) else email_data
                            if isinstance(emails_to_check, list):
                                for e in emails_to_check:
                                    if isinstance(e, str) and is_valid_email(e):
                                        lead_data["email"] = e
                                        lead_data["email_step"] = "Step 2: JSON-LD"
                                        break
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue

    # STEP 4: Semantic Blocks
    semantic_blocks = soup.find_all(['footer', 'header', 'address']) + soup.find_all(class_=re.compile(r'contact|footer|info|meta', re.I)) + soup.find_all(id=re.compile(r'contact|footer|info|meta', re.I))
    for block in semantic_blocks:
        text = block.get_text(separator=" ", strip=True)
        if not lead_data["phone_number"]:
            phones = phone_regex.findall(text)
            valid_phones = [p for p in phones if is_valid_phone(p)]
            if valid_phones: 
                lead_data["phone_number"] = valid_phones[0].strip()
                lead_data["phone_step"] = "Step 4: Semantic Blocks"
        if not lead_data["email"]:
            emails = email_regex.findall(text)
            if emails:
                valid_emails = [e for e in emails if is_valid_email(e)]
                if valid_emails:
                    lead_data["email"] = valid_emails[0]
                    lead_data["email_step"] = "Step 4: Semantic Blocks"

    # STEP 5 & 6: Content & Raw Fallback
    if not lead_data["phone_number"]:
        phones = phone_regex.findall(text_content)
        valid_phones = [p for p in phones if is_valid_phone(p)]
        if valid_phones: 
            lead_data["phone_number"] = valid_phones[0].strip()
            lead_data["phone_step"] = "Step 5: Visible Content"
    if not lead_data["email"]:
        emails = email_regex.findall(text_content)
        if emails:
            valid_emails = [e for e in emails if is_valid_email(e)]
            if valid_emails:
                lead_data["email"] = valid_emails[0]
                lead_data["email_step"] = "Step 5: Visible Content"
    if not lead_data["phone_number"]:
        phones = phone_regex.findall(html)
        valid_phones = [p for p in phones if is_valid_phone(p)]
        if valid_phones: 
            lead_data["phone_number"] = valid_phones[0].strip()
            lead_data["phone_step"] = "Step 6: Raw Regex"
    if not lead_data["email"]:
        raw_emails = email_regex.findall(html)
        if raw_emails:
            valid_emails = [e for e in raw_emails if is_valid_email(e)]
            if valid_emails:
                lead_data["email"] = valid_emails[0]
                lead_data["email_step"] = "Step 6: Raw Regex"

    return lead_data

# ==========================================
# DOMAIN HUNTER (HIGHEST QUALITY OVERRIDE)
# ==========================================
def get_step_score(step_str: str) -> int:
    if not step_str or "Failed" in step_str: return 0
    if "Step 1" in step_str: return 100
    if "Step 2" in step_str: return 80
    if "Step 4" in step_str: return 60
    if "Step 5" in step_str: return 40
    if "Step 6" in step_str: return 20
    return 0

async def extract_domain_tier1(base_url: str, user_prompt: str = "", topical_keywords: list = None) -> dict:
    if topical_keywords is None:
        topical_keywords = []
        
    html_home = await fetch_html_fast(base_url)
    
    master_lead = {
        "source_url": base_url,
        "email": None, "phone_number": None, 
        "email_step": "Failed", "phone_step": "Failed",
        "qualification_score": 0.0,
        "score_breakdown": {}
    }

    if not html_home:
        return master_lead

    # 🛑 STAGE 1: THE TRUTH FILTER
    # Bounces garbage entities before math is ever applied
    is_verified, gate_reason = verify_entity_gate(html_home, base_url, user_prompt, topical_keywords)
    if not is_verified:
        raise ValueError(f"Rejected: {gate_reason} (Score: 0.0)")

    # 🛑 STAGE 2: THE PROBABILISTIC RANKER
    lead_score, rejection_reason, score_breakdown = calculate_probabilistic_score(html_home, base_url, user_prompt, topical_keywords)
    
    if lead_score < 40.0:
        raise ValueError(f"Rejected: {rejection_reason} (Score: {lead_score:.1f})")
        
    master_lead["qualification_score"] = lead_score
    master_lead["score_breakdown"] = score_breakdown
        
    soup = BeautifulSoup(html_home, "html.parser")
    subpages = set()
    keywords = ['contact', 'about', 'connect', 'reach']
    
    base_domain = urllib.parse.urlparse(base_url).netloc.replace('www.', '').lower()

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].lower()
        if any(k in href for k in keywords):
            if any(href.split('?')[0].endswith(ext) for ext in ['.jpg', '.png', '.jpeg', '.pdf', '.css', '.js']):
                continue
            
            full_url = urllib.parse.urljoin(base_url, a_tag['href'])
            link_domain = urllib.parse.urlparse(full_url).netloc.replace('www.', '').lower()
            if base_domain == link_domain:
                full_url = urllib.parse.urlunparse(urllib.parse.urlparse(full_url)._replace(fragment=""))
                subpages.add(full_url)
                
    for fallback in ['/contact/', '/about/']:
        subpages.add(urllib.parse.urljoin(base_url, fallback))
    
    def sort_key(url):
        url_lower = url.lower()
        score = 2
        if 'contact' in url_lower: score = 0
        elif 'about' in url_lower: score = 1
        return (score, len(url))

    sorted_sub_urls = sorted(list(subpages), key=sort_key)[:3]
    
    tasks = [fetch_html_fast(u) for u in sorted_sub_urls]
    sub_htmls = await asyncio.gather(*tasks)
    
    execution_queue = []
    for sub_html, sub_url in zip(sub_htmls, sorted_sub_urls):
        if sub_html: execution_queue.append((sub_html, sub_url))
    execution_queue.append((html_home, base_url))
    
    best_email_score = -1
    best_phone_score = -1

    for page_html, page_url in execution_queue:
        page_data = extract_lead_data(page_html, page_url)
        path = urllib.parse.urlparse(page_url).path
        if path == "": path = "/"
        
        if page_data["email"]:
            score = get_step_score(page_data["email_step"])
            if score > best_email_score:
                master_lead["email"] = page_data["email"]
                best_email_score = score
                master_lead["email_step"] = f"{page_data['email_step']} (via {path})" if path != "/" else page_data["email_step"]
                
        if page_data["phone_number"]:
            score = get_step_score(page_data["phone_step"])
            if score > best_phone_score:
                master_lead["phone_number"] = page_data["phone_number"]
                best_phone_score = score
                master_lead["phone_step"] = f"{page_data['phone_step']} (via {path})" if path != "/" else page_data["phone_step"]
                
    return master_lead