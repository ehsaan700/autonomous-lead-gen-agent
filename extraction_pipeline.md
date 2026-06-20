# 6-STEP CONTACT EXTRACTION PROTOCOL

This protocol defines the absolute execution priority for extracting contact information from a page's raw HTML. The scraper must stop processing and return the data as soon as a valid email address is found (Short-Circuit Evaluation).

## Step 1: Direct Mailto Anchors (Highest Confidence)
- **Target:** `<a href^="mailto:">` tags.
- **Action:** Extract the exact string following `mailto:`. 
- **Why:** This is an explicit, human-designed email link. It has a zero false-positive rate.

## Step 2: Structured JSON-LD Data Schema
- **Target:** `<script type="application/ld+json">` elements.
- **Action:** Parse the raw text inside as JSON. Search for keys like `"email"`, `"telephone"`, or `"contactPoint"` within schemas matching `"@type": "LocalBusiness"`, `"Organization"`, or `"ProfessionalService"`.
- **Why:** Modern sites use structured metadata for SEO. If it is here, it is accurate, formatted, and doesn't require messy parsing.

## Step 3: Social Profile Links
- **Target:** Anchor tags pointing to dominant social platforms.
- **Action:** Extract full URLs containing:
  - `linkedin.com/company/` or `linkedin.com/in/`
  - `facebook.com/`
  - `instagram.com/`
  - `twitter.com/` or `x.com/`
- **Why:** Even if an email isn't directly on the page, these URLs provide an immediate secondary data point for your final CSV lead sheet.

## Step 4: High-Probability Semantic Blocks
- **Target:** Specific HTML5 structural tags and attributes:
  - `<footer>`, `<header>`, `<address>`
  - Elements with classes/IDs containing `contact`, `footer`, `info`, or `meta`.
- **Action:** Run a targeted regex scan exclusively within the raw inner text of these specific blocks.

## Step 5: Visible Content Paragraphs (Regex Fallback)
- **Target:** Pure user-facing text tags: `<p>`, `<span>`, `<li>`, `<h1>` through `<h6>`.
- **Action:** Extract the inner text, strip HTML tags, and run the standard email regex: `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`
- **Why:** Captures emails displayed in plain text within body copy without scanning hidden layout structures.

## Step 6: Full-Page Raw Text Regex (The Last Resort)
- **Target:** The entire raw, unparsed HTML body response.
- **Action:** Run the global email regex pattern.
- **Constraint:** Filter out common structural false-positives (e.g., strings ending in `.png`, `.jpg`, `.svg`, `w3.org`, or script filenames).
- **Why:** A catch-all safety net for unformatted or poorly coded websites.