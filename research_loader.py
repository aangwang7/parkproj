

import os
import json
import hashlib
import re

PAPERS_DIR   = os.path.join(os.path.dirname(__file__), "papers")
CACHE_FILE   = os.path.join(os.path.dirname(__file__), ".paper_cache.json")

# ── PDF TEXT EXTRACTION ───────────────────────────────────

def extract_text_from_pdf(filepath: str) -> str:
    """Extract raw text from a PDF using pypdf (pure Python, no system deps)."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(filepath)
        pages  = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
        return "\n\n".join(pages)
    except ImportError:
        raise RuntimeError("pypdf not installed. Add 'pypdf' to requirements.txt.")
    except Exception as e:
        return f"[Could not extract text: {e}]"


def file_hash(filepath: str) -> str:
    """MD5 hash of file contents — used to detect if a paper changed."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_pdf_text(raw: str) -> str:
    """
    Basic cleanup of raw PDF extraction:
    - Remove excessive whitespace / blank lines
    - Stitch hyphenated line-breaks back together
    - Drop page headers/footers (lines < 4 words that repeat)
    """
    # Stitch hyphenated breaks: "neuro-\ndegenerative" → "neurodegenerative"
    text = re.sub(r"-\n(\w)", r"\1", raw)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip very short lines (likely page numbers / headers)
    lines  = text.splitlines()
    cleaned = [l for l in lines if len(l.split()) >= 3 or l.strip() == ""]
    return "\n".join(cleaned).strip()


# ── CACHE ─────────────────────────────────────────────────

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_cache(cache: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


# ── MAIN LOADER ───────────────────────────────────────────

def load_all_papers(max_chars_per_paper: int = 12000) -> str:
    """
    Scan /papers directory, extract text from every PDF, cache results.
    Returns a formatted string ready to inject into the K2 system prompt.

    max_chars_per_paper: truncation limit per paper to stay within context window.
    Increase if K2's context allows; decrease if you add many papers.
    """
    if not os.path.isdir(PAPERS_DIR):
        os.makedirs(PAPERS_DIR)
        return "[No papers loaded — add PDFs to the /papers folder.]"

    pdf_files = sorted([
        f for f in os.listdir(PAPERS_DIR)
        if f.lower().endswith(".pdf")
    ])

    if not pdf_files:
        return "[No PDF papers found in /papers folder.]"

    cache   = load_cache()
    changed = False
    sections = []

    for filename in pdf_files:
        filepath = os.path.join(PAPERS_DIR, filename)
        fhash    = file_hash(filepath)
        title    = os.path.splitext(filename)[0].replace("_", " ").replace("-", " ").title()

        # Use cache if file hasn't changed
        if filename in cache and cache[filename]["hash"] == fhash:
            text = cache[filename]["text"]
            print(f"[research_loader] ✓ (cached)  {filename}")
        else:
            print(f"[research_loader] ↻ (loading) {filename}")
            raw  = extract_text_from_pdf(filepath)
            text = clean_pdf_text(raw)
            # Truncate to limit
            if len(text) > max_chars_per_paper:
                text = text[:max_chars_per_paper] + f"\n\n[... truncated at {max_chars_per_paper} chars]"
            cache[filename] = {"hash": fhash, "text": text}
            changed = True

        sections.append(f"--- PAPER: {title} ---\nFile: {filename}\n\n{text}\n")

    if changed:
        save_cache(cache)

    header = (
        "=== SUPPLEMENTARY RESEARCH CORPUS ===\n"
        f"({len(sections)} paper(s) loaded from /papers directory)\n\n"
    )
    footer = "\n=== END SUPPLEMENTARY CORPUS ==="

    return header + "\n\n".join(sections) + footer


# ── SINGLETON — loaded once at Flask startup ───────────────

_loaded_papers: str | None = None

def get_research_corpus() -> str:
    """
    Call this from app.py. Papers are loaded once at startup and cached
    in memory. Restart the server to pick up newly added PDFs.
    """
    global _loaded_papers
    if _loaded_papers is None:
        print("[research_loader] Loading papers...")
        _loaded_papers = load_all_papers()
        print(f"[research_loader] Done. {len(_loaded_papers):,} chars loaded.")
    return _loaded_papers