import os
import re
import json
import datetime
import urllib.request
import xml.etree.ElementTree as ET
from google import genai
from google.genai import types

# 1. Specialized feeds covering your 5 Core Jurisdictional Pillars
FEEDS = [
    # ICJ, Courts & UN Legal
    "https://news.un.org/feed/subscribe/en/news/topic/law-and-crime/feed/rss.xml",
    # IHL & Armed Conflict
    "https://blogs.icrc.org/law-and-policy/feed/",
    # Public International Law & Adjudication
    "https://www.ejiltalk.org/feed/",
    "https://opiniojuris.org/feed/",
    "https://voelkerrechtsblog.org/feed/",
    # International Economic, Trade & Investment Law
    "https://ielp.worldtradelaw.net/feed.xml",
]

ALLOWED_FORUMS = [
    "ICJ & Adjudication",
    "State Responsibility & Sovereignty",
    "Law of the Sea (UNCLOS)",
    "Armed Conflict & IHL",
    "International Trade & Sanctions"
]

SEEN_FILE = "scripts/seen_urls.json"
POSTS_DIR = "_posts"

def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_seen(seen):
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen)), f, indent=2)

def fetch_feed_items():
    items = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    for url in FEEDS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                xml_data = resp.read()
                root = ET.fromstring(xml_data)
                
                # Support both standard RSS <item> and Atom <entry>
                rss_items = root.findall(".//item")
                if not rss_items:
                    rss_items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
                
                for item in rss_items:
                    title = item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or ""
                    link = item.findtext("link") or ""
                    if not link:
                        link_elem = item.find("{http://www.w3.org/2005/Atom}link")
                        if link_elem is not None and "href" in link_elem.attrib:
                            link = link_elem.attrib["href"]
                    
                    description = (
                        item.findtext("description") 
                        or item.findtext("{http://www.w3.org/2005/Atom}summary")
                        or item.findtext("{http://www.w3.org/2005/Atom}content")
                        or ""
                    )
                    
                    # Clean simple HTML tags from RSS summary
                    description = re.sub(r"<[^>]+>", " ", description)
                    description = " ".join(description.split())
                    
                    if link and title:
                        items.append({
                            "title": title.strip(),
                            "link": link.strip(),
                            "summary": description[:600].strip()
                        })
        except Exception as e:
            print(f"Warning: Failed fetching {url}: {e}")
            continue
            
    return items

def generate_article(item, client, today_str):
    prompt = f"""
You are the Senior Editor of 'International Law Now' (internationallaw.now), a digital review providing rapid, rigorous doctrinal analysis of public international law disputes, arbitral awards, advisory proceedings, trade/investment law, and international humanitarian law.

You need to draft a complete, production-ready dispatch analyzing the following legal development:

Article Title: {item['title']}
Source Reference: {item['link']}
Raw Summary: {item['summary']}

CRITICAL FORMATTING INSTRUCTIONS:
1. Output MUST start with valid YAML frontmatter matching this exact template:
---
layout: post
title: "SCHOLARLY_TITLE_HERE"
date: {today_str}
jurisdiction: "EXACT_FORUM"
summary: "ONE_OR_TWO_SENTENCE_ANALYTICAL_SUMMARY_HERE"
---

2. 'jurisdiction' MUST strictly be one of these five exact options:
- "ICJ & Adjudication"
- "State Responsibility & Sovereignty"
- "Law of the Sea (UNCLOS)"
- "Armed Conflict & IHL"
- "International Trade & Sanctions"

3. 'summary' must be a single, precise thesis sentence explaining the legal controversy and the applicable legal instrument (e.g. UNCLOS Art 121, ARSIWA Art 8, Geneva Additional Protocol I, VCLT Art 31).

4. Body Structure:
- Start the first paragraph with a bold uppercase dateline indicating the relevant legal forum city (e.g., **THE HAGUE** —, **GENEVA** —, **HAMBURG** —, **WASHINGTON** —, or **NEW YORK** —).
- Frame the central legal question in bold within the first two paragraphs.
- Include structured numbered sections (e.g., '## 1. Jurisdictional Threshold and Normative Conflict', '## 2. Doctrinal Assessment under [Relevant Treaty/Custom]', '## 3. Systemic Implications').
- Where applicable, include a Markdown comparison table summarizing standard of review, statutory thresholds, or conflicting state positions.
- Cite specific legal instruments, compromissory clauses, or landmark jurisprudence (e.g., Nicaragua, Corfu Channel, Chagos, Ferrini, Gabčíkovo-Nagymaros).
- Do NOT wrap the entire answer in outer markdown backticks (```markdown). Output raw text starting with the opening '---'.
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text

def slugify(text):
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:45]

def clean_output(text):
    raw = text.strip()
    # Strip any accidental wrapping code fences from LLM output
    if raw.startswith("```markdown"):
        raw = raw[len("```markdown"):].strip()
    elif raw.startswith("```"):
        raw = raw[3:].strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    return raw

def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not configured.")
        
    client = genai.Client(api_key=api_key)
    seen = load_seen()
    items = fetch_feed_items()
    
    # Isolate unhandled events
    new_items = [i for i in items if i["link"] not in seen]
    print(f"Retrieved {len(items)} feed items; {len(new_items)} are new.")
    
    if not new_items:
        print("No new updates found.")
        return

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    os.makedirs(POSTS_DIR, exist_ok=True)
    
    # Process the top fresh item per run to ensure editorial quality
    for item in new_items[:1]:
        print(f"Generating dispatch for: {item['title']}")
        article_text = generate_article(item, client, today_str)
        cleaned_post = clean_output(article_text)
        
        # Verify valid frontmatter was produced
        if not cleaned_post.startswith("---") or "jurisdiction:" not in cleaned_post:
            print("Failed validation: Generated text is missing required YAML frontmatter.")
            continue
            
        slug = slugify(item["title"])
        post_path = os.path.join(POSTS_DIR, f"{today_str}-{slug}.md")
        
        with open(post_path, "w", encoding="utf-8") as f:
            f.write(cleaned_post + "\n")
            
        seen.add(item["link"])
        print(f"Successfully committed dispatch: {post_path}")

    save_seen(seen)

if __name__ == "__main__":
    main()
