"""One-time quotes ingest.

Pulls curated quotes from Wikiquote (~42 authors) plus two full-text
Project Gutenberg works (Emerson's Essays, Thoreau's Walden), cleans,
dedupes, and writes /data/quotes.json. The operator copies that file
to the repo root and commits it.

Run inside the backend container:
    docker exec personal-os-api python -m app.scripts.ingest_quotes
"""
from __future__ import annotations

import json
import random
import re
import sys
import time
from pathlib import Path

import httpx

try:
    import wikiquote
except ImportError:
    print("missing dep: pip install wikiquote", file=sys.stderr)
    raise

OUTPUT = Path("/data/quotes.json")
UA = "personal-os-ingest/1.0 (+https://personal-os-sage-tau.vercel.app)"
WIKIQUOTE_SLEEP = 0.6
RANDOM_SEED = 1729

# (wikiquote page name, display author)
AUTHORS: list[tuple[str, str]] = [
    # Classical fiction
    ("Jane Austen", "Jane Austen"),
    ("Herman Melville", "Herman Melville"),
    ("Leo Tolstoy", "Leo Tolstoy"),
    ("Fyodor Dostoyevsky", "Fyodor Dostoevsky"),
    ("Charles Dickens", "Charles Dickens"),
    ("George Eliot", "George Eliot"),
    ("Thomas Hardy", "Thomas Hardy"),
    ("Joseph Conrad", "Joseph Conrad"),
    ("Mark Twain", "Mark Twain"),
    ("Oscar Wilde", "Oscar Wilde"),
    ("Victor Hugo", "Victor Hugo"),
    ("Gustave Flaubert", "Gustave Flaubert"),
    ("Nathaniel Hawthorne", "Nathaniel Hawthorne"),
    ("Edgar Allan Poe", "Edgar Allan Poe"),
    ("Henry James", "Henry James"),
    # Modernist / early 20th c.
    ("Virginia Woolf", "Virginia Woolf"),
    ("James Joyce", "James Joyce"),
    ("F. Scott Fitzgerald", "F. Scott Fitzgerald"),
    ("Ernest Hemingway", "Ernest Hemingway"),
    ("John Steinbeck", "John Steinbeck"),
    ("William Faulkner", "William Faulkner"),
    ("Willa Cather", "Willa Cather"),
    ("Franz Kafka", "Franz Kafka"),
    ("Hermann Hesse", "Hermann Hesse"),
    ("Gabriel García Márquez", "Gabriel García Márquez"),
    ("Jorge Luis Borges", "Jorge Luis Borges"),
    ("Italo Calvino", "Italo Calvino"),
    ("Vladimir Nabokov", "Vladimir Nabokov"),
    # Contemporary
    ("Toni Morrison", "Toni Morrison"),
    ("James Baldwin", "James Baldwin"),
    ("Flannery O'Connor", "Flannery O'Connor"),
    ("Cormac McCarthy", "Cormac McCarthy"),
    ("Ursula K. Le Guin", "Ursula K. Le Guin"),
    ("Ray Bradbury", "Ray Bradbury"),
    ("Kurt Vonnegut", "Kurt Vonnegut"),
    ("Annie Dillard", "Annie Dillard"),
    ("Joan Didion", "Joan Didion"),
    # Poets
    ("Walt Whitman", "Walt Whitman"),
    ("Emily Dickinson", "Emily Dickinson"),
    ("Rainer Maria Rilke", "Rainer Maria Rilke"),
    ("William Butler Yeats", "W.B. Yeats"),
    ("T. S. Eliot", "T.S. Eliot"),
    ("Mary Oliver", "Mary Oliver"),
    ("Langston Hughes", "Langston Hughes"),
]

# (gutenberg id, display author, display source)
GUTENBERG_WORKS: list[tuple[int, str, str]] = [
    (2945, "Ralph Waldo Emerson", "Essays: First Series"),
    (205, "Henry David Thoreau", "Walden"),
]

# Characters that indicate wiki markup residue or footnote cruft.
BAD_SUBSTRINGS = ("[", "]", "Ibid", "op. cit", "http://", "https://", "Wikipedia", "wikisource")

SMART_QUOTES = '"“”‘’„‟«»'


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # Strip wrapping quote marks (common on Wikiquote entries).
    while text and text[0] in SMART_QUOTES and text[-1] in SMART_QUOTES:
        text = text[1:-1].strip()
    # Strip surrounding single quotes too if they wrap the whole line.
    if text.startswith("'") and text.endswith("'") and text.count("'") == 2:
        text = text[1:-1].strip()
    return text


def accept(text: str) -> bool:
    # Thought card now occupies the bottom 2/3 of the left stack; room for
    # longer quotes. Still cap at 500 to avoid anything novel-length.
    if not (40 <= len(text) <= 500):
        return False
    if any(sub in text for sub in BAD_SUBSTRINGS):
        return False
    # Must end in sentence-terminal punctuation.
    if text[-1] not in ".!?":
        return False
    # Drop obvious list / table / heading fragments.
    if text.count(":") > 3:
        return False
    return True


def dedupe(quotes: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for q in quotes:
        key = re.sub(r"[^a-z0-9 ]", "", q["text"].lower())[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out


def fetch_wikiquote(page: str, display_author: str, max_quotes: int = 30) -> list[dict]:
    print(f"  wikiquote: {page} …", end=" ", flush=True)
    try:
        raw = wikiquote.quotes(page, max_quotes=max_quotes, lang="en")
    except Exception as exc:  # noqa: BLE001
        print(f"skip ({exc.__class__.__name__}: {exc})")
        return []
    cleaned = []
    for line in raw:
        txt = clean_text(line)
        if accept(txt):
            cleaned.append({"text": txt, "author": display_author, "source": None})
    print(f"{len(cleaned)} kept of {len(raw)}")
    return cleaned


def strip_gutenberg_boilerplate(body: str) -> str:
    start_re = re.compile(r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.I)
    end_re = re.compile(r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.I)
    s = start_re.search(body)
    e = end_re.search(body)
    if s:
        body = body[s.end():]
    if e:
        body = body[: e.start()]
    return body


def fetch_gutenberg(book_id: int, display_author: str, display_source: str) -> list[dict]:
    url = f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"
    print(f"  gutenberg: {display_author} · {display_source} ({book_id}) …", end=" ", flush=True)
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=30, follow_redirects=True)
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"skip ({exc.__class__.__name__}: {exc})")
        return []
    body = strip_gutenberg_boilerplate(r.text)
    paras = [p.strip() for p in re.split(r"\n{2,}", body)]
    cleaned = []
    for p in paras:
        # Collapse single-newlines inside paragraphs to spaces.
        flat = re.sub(r"\s+", " ", p).strip()
        if accept(flat):
            cleaned.append({"text": flat, "author": display_author, "source": display_source})
    print(f"{len(cleaned)} kept of {len(paras)}")
    return cleaned


def main() -> int:
    random.seed(RANDOM_SEED)
    all_quotes: list[dict] = []

    print(f"Ingesting from Wikiquote ({len(AUTHORS)} authors)…")
    for page, display in AUTHORS:
        all_quotes.extend(fetch_wikiquote(page, display))
        time.sleep(WIKIQUOTE_SLEEP)

    print(f"\nIngesting from Project Gutenberg ({len(GUTENBERG_WORKS)} works)…")
    for book_id, author, source in GUTENBERG_WORKS:
        all_quotes.extend(fetch_gutenberg(book_id, author, source))
        time.sleep(1.0)

    print(f"\nTotal raw: {len(all_quotes)}")
    deduped = dedupe(all_quotes)
    print(f"After dedupe: {len(deduped)}")

    random.shuffle(deduped)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(deduped, ensure_ascii=False, indent=0))
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"Wrote {OUTPUT} — {len(deduped)} quotes, {size_kb:.1f} KB")

    # Small breakdown by author
    from collections import Counter
    by_author = Counter(q["author"] for q in deduped)
    print("\nPer-author counts:")
    for a, n in by_author.most_common():
        print(f"  {n:4d}  {a}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
