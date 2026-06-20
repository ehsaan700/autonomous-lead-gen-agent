import httpx
import asyncio
import re
import json
import urllib.parse
from bs4 import BeautifulSoup

# ==========================================
# TIER 1: FAST FETCH
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
        # Suppress expected 404s for common subpages so we don't spam the console
        # if not url.rstrip('/').endswith(('contact', 'about', 'contact-us')):
            #print(f"[Tier 1 Failed] {url} - {str(e)}")
        return None

# ==========================================
# THE 5-STEP PARSER (Strictly Aligned)
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
        
        # Immediate block for empty or malformed strings
        if "@" not in email_lower or "." not in email_lower.split("@")[-1]: 
            return False
            
        invalid_extensions = ('.png', '.jpg', '.jpeg', '.svg', '.gif', '.js', '.css', 'w3.org')
        dummy_domains = (
            'example.com', 'domain.com', 'yoursite.com', 'email.com', 
            'sentry.io', 'yourcompany.com', 'company.com', 'mysite.com'
        )
        
        if email_lower.endswith(invalid_extensions): return False
        if email_lower.startswith(('user@', 'name@', 'info@your', 'you@')): return False
        
        for dummy in dummy_domains:
            if dummy in email_lower: return False
            
        return True

    def is_valid_phone(phone_str: str, is_tel: bool = False) -> bool:
        clean_str = re.sub(r'\D', '', phone_str)
        if not (10 <= len(clean_str) <= 15): return False
        
        if not is_tel:
            # 1. UNIX Timestamp Killer 
            if phone_str.strip() == clean_str and not phone_str.strip().startswith('+'):
                return False
                
            # 2. Skewed Separator Blocks (Asset IDs, ISBNs)
            if re.search(r'\d{5,}[\s.-]+', phone_str) or re.search(r'[\s.-]+\d{5,}', phone_str):
                return False
            
            # 3. Block text masquerading as numbers
            if re.search(r'[a-zA-Z]', phone_str): return False
            
            # 4. Block pure space-separated chunks (Fixes: "483 876 770 1654")
            if phone_str.count(' ') > 2 and not any(c in phone_str for c in '+()-'):
                return False
                
        # 5. Global dummy blocks
        if re.search(r'(\d)\1{6,}', clean_str): return False
        if "123456789" in clean_str or "098765432" in clean_str: return False
        if clean_str.startswith("0000"): return False
        if clean_str.startswith("123456"): return False
            
        return True

    # ---------------------------------------------------------
    # STEP 1A: Direct Mailto Anchors (Emails)
    # ---------------------------------------------------------
    if not lead_data["email"]:
        for a_tag in soup.find_all('a', href=re.compile(r'(?i)^\s*mailto:')):
            raw_email = re.sub(r'(?i)^\s*mailto:\s*', '', a_tag['href']).split('?')[0].strip()
            raw_email = urllib.parse.unquote(raw_email)
            if is_valid_email(raw_email):
                lead_data["email"] = raw_email
                lead_data["email_step"] = "Step 1: Mailto"
                break

    # ---------------------------------------------------------
    # STEP 1B: Direct Tel Anchors (Phones)
    # ---------------------------------------------------------
    if not lead_data["phone_number"]:
        for a_tag in soup.find_all('a', href=re.compile(r'(?i)^\s*tel:')):
            raw_phone = re.sub(r'(?i)^\s*tel:\s*', '', a_tag['href']).split('?')[0].strip()
            raw_phone = urllib.parse.unquote(raw_phone)
            if is_valid_phone(raw_phone, is_tel=True):
                lead_data["phone_number"] = raw_phone
                lead_data["phone_step"] = "Step 1: Tel Anchor"
                break
                
    # ---------------------------------------------------------
    # STEP 1C: Cloudflare Obfuscation Bypass
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
    # STEP 2: Structured JSON-LD Data Schema
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
    # STEP 4: High-Probability Semantic Blocks
    # ---------------------------------------------------------
    semantic_blocks = soup.find_all(['footer', 'header', 'address']) + \
                      soup.find_all(class_=re.compile(r'contact|footer|info|meta', re.I)) + \
                      soup.find_all(id=re.compile(r'contact|footer|info|meta', re.I))
    
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

    # ---------------------------------------------------------
    # STEP 5: Visible Content Paragraphs
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
    # STEP 6: Full Page Raw Regex Fallback 
    # ---------------------------------------------------------
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
    """Assigns a confidence score to extraction steps. Higher is better."""
    if not step_str or "Failed" in step_str: return 0
    if "Step 1" in step_str: return 100
    if "Step 2" in step_str: return 80
    if "Step 4" in step_str: return 60
    if "Step 5" in step_str: return 40
    if "Step 6" in step_str: return 20
    return 0

async def extract_domain_tier1(base_url: str) -> dict:
    html_home = await fetch_html_fast(base_url)
    
    master_lead = {
        "source_url": base_url,
        "email": None, "phone_number": None, 
        "email_step": "Failed", "phone_step": "Failed"
    }

    if not html_home:
        return master_lead
        
    soup = BeautifulSoup(html_home, "html.parser")
    subpages = set()
    keywords = ['contact', 'about', 'connect', 'reach']
    
    base_domain = urllib.parse.urlparse(base_url).netloc.replace('www.', '').lower()

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].lower()
        if any(k in href for k in keywords):
            # Block static files masquerading as pages
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
    
    # Priority Execution Queue (Contact -> About -> Homepage)
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
        
        # Override Email if we found a higher-confidence source
        if page_data["email"]:
            score = get_step_score(page_data["email_step"])
            if score > best_email_score:
                master_lead["email"] = page_data["email"]
                best_email_score = score
                master_lead["email_step"] = f"{page_data['email_step']} (via {path})" if path != "/" else page_data["email_step"]
                
        # Override Phone if we found a higher-confidence source
        if page_data["phone_number"]:
            score = get_step_score(page_data["phone_step"])
            if score > best_phone_score:
                master_lead["phone_number"] = page_data["phone_number"]
                best_phone_score = score
                master_lead["phone_step"] = f"{page_data['phone_step']} (via {path})" if path != "/" else page_data["phone_step"]
                
    return master_lead