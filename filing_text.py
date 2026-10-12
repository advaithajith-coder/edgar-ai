"""The written part of a 10-K (risk factors, MD&A, market risk) as short searchable passages.

Flow: the filing's main HTML document → plain-text lines → the three sections (found by their
"Item 1A / 7 / 7A" headings) → ~150-word passages → a DuckDB table with a full-text (BM25) index.
Search runs locally in DuckDB, so it costs no Groq tokens; only the few trimmed passages the
agent asks for are sent to the model.
"""

import re

import duckdb
import lxml.html
import pandas as pd

SECTIONS = {"1a": "Risk factors", "7": "MD&A", "7a": "Market risk"}
ITEM_HEADING = re.compile(r"^item\s*(\d{1,2}[a-c]?)\b", re.I)
PASSAGE_WORDS = 150      # target passage length when indexing
RESULT_WORDS = 90        # words kept per passage when sending it to the model (lean on tokens)
RESULTS = 3              # passages per search
BLOCKS = ("p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6", "table")
STOPWORDS = set("a an and are as at be by did do does for from has have how in is it its of on or "
                "the their to was were what when where which why with".split())


# ---------------------------------------------------------------- HTML → sections → passages
def document_lines(html: bytes) -> list[str]:
    """Visible text of the filing, one line per block, without the hidden XBRL header and
    without lines that are mostly numbers (table rows - the statements already cover those)."""
    doc = lxml.html.fromstring(html)
    for hidden in doc.xpath('//*[contains(translate(@style, " ", ""), "display:none")]'):
        hidden.drop_tree()
    for el in doc.iter(*BLOCKS):
        el.tail = "\n" + (el.tail or "")
    lines = []
    for raw in doc.text_content().split("\n"):
        line = re.sub(r"\s+", " ", raw.replace("\xa0", " ")).strip()
        letters = sum(c.isalpha() for c in line)
        if letters >= 3 and letters >= 0.5 * len(line.replace(" ", "")):
            lines.append(line)
    return lines


def page_furniture(lines: list[str]) -> set[str]:
    """Running page headers/footers ("PART I", "Item 1A", "Apple Inc. | 2025 Form 10-K | 6"):
    short lines that repeat on many pages once page numbers are ignored."""
    counts: dict[str, int] = {}
    for line in lines:
        if len(line) < 100:
            key = re.sub(r"\d+", "#", line.lower())
            counts[key] = counts.get(key, 0) + 1
    return {key for key, n in counts.items() if n >= 4}


def split_sections(lines: list[str]) -> dict[str, list[str]]:
    """Lines of each wanted section. Each heading appears in the table of contents and again at the
    real section (and some filings repeat it as a running page header), so consecutive headings of
    the same item are merged and, per item, the span with the most text wins."""
    headings = []
    for i, line in enumerate(lines):
        if len(line) < 250 and (m := ITEM_HEADING.match(line)):
            item = m.group(1).lower()
            if not headings or headings[-1][1] != item:   # a repeat of the same item continues it
                headings.append((i, item))
    furniture = page_furniture(lines)
    best: dict[str, tuple[list[str], int]] = {}   # item → (body lines, characters)
    for n, (start, item) in enumerate(headings):
        if item not in SECTIONS:
            continue
        end = headings[n + 1][0] if n + 1 < len(headings) else len(lines)
        body = [line for line in lines[start + 1:end]
                if not ITEM_HEADING.match(line) and re.sub(r"\d+", "#", line.lower()) not in furniture]
        size = sum(len(line) for line in body)
        if size > best.get(item, ([], 0))[1]:
            best[item] = (body, size)
    # skip stubs like "See Item 7 of this report"
    return {SECTIONS[item]: body for item, (body, size) in best.items() if size > 1500}


def is_heading(line: str) -> bool:
    """A short line that doesn't read like a sentence or a bullet point."""
    return (len(line.split()) <= 12 and line[0].isalnum() and not line[0].islower()
            and not line.endswith((".", ":", ";", ",")))


def passages(section: str, lines: list[str]) -> list[dict]:
    """Group paragraphs into ~PASSAGE_WORDS-word passages, remembering the sub-heading above them."""
    out, heading, words = [], "", []

    def flush():
        if words:
            out.append({"section": section, "heading": heading, "text": " ".join(words)})
            words.clear()

    for line in lines:
        if is_heading(line):
            flush()
            heading = line
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            words.extend(sentence.split())
            if len(words) >= PASSAGE_WORDS:
                flush()
        if len(words) >= PASSAGE_WORDS * 0.7:   # end passages at paragraph breaks when possible
            flush()
    flush()
    return out


def filing_passages(html: bytes) -> pd.DataFrame:
    """Passages from the risk factors, MD&A and market risk sections. If those sections can't be
    found (unusual heading layout), falls back to the whole document."""
    lines = document_lines(html)
    furniture = page_furniture(lines)
    sections = split_sections(lines) or {
        "10-K": [line for line in lines if re.sub(r"\d+", "#", line.lower()) not in furniture]}
    rows = [p for name, body in sections.items() for p in passages(name, body)]
    df = pd.DataFrame(rows, columns=["section", "heading", "text"])
    df.insert(0, "passage_id", range(1, len(df) + 1))
    return df


# ---------------------------------------------------------------- index + search
def index_passages(con: duckdb.DuckDBPyConnection, table: str) -> None:
    """Build DuckDB's full-text index on a passages table (no-op if the extension isn't available;
    search then falls back to simple keyword counting)."""
    try:
        con.execute("INSTALL fts")
        con.execute("LOAD fts")
        con.execute(f"PRAGMA create_fts_index('{table}', 'passage_id', 'heading', 'text', overwrite=1)")
    except duckdb.Error:
        pass


def _terms(query: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9&]+", query.lower()) if t not in STOPWORDS and len(t) > 1]


def trim(text: str, terms: list[str], limit: int = RESULT_WORDS) -> str:
    """Keep the sentences that mention the search terms (in their original order), up to `limit` words."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    stems = [t[:5] for t in terms]   # crude stemming: "margins" ~ "margin", "growth" ~ "grow"
    scored = sorted(range(len(sentences)),
                    key=lambda i: -sum(s in sentences[i].lower() for s in stems))
    keep, count = set(), 0
    for i in scored:
        n = len(sentences[i].split())
        if count and count + n > limit:
            continue
        keep.add(i)
        count += n
        if count >= limit:
            break
    picked = [sentences[i] for i in sorted(keep)]
    if len(picked) == 1 and len(picked[0].split()) > limit:   # one very long sentence
        picked = [" ".join(picked[0].split()[:limit]) + " …"]
    out = picked[0]
    for prev, i in zip(sorted(keep), sorted(keep)[1:]):
        out += (" " if i == prev + 1 else " … ") + sentences[i]
    return out


def search(con: duckdb.DuckDBPyConnection, table: str, query: str, section: str = "",
           k: int = RESULTS) -> pd.DataFrame:
    """Top-k passages for the query (BM25), optionally within one section; text trimmed to the
    sentences that matter."""
    where = "WHERE score IS NOT NULL" + (" AND section ILIKE ?" if section else "")
    params = [query] + ([f"%{section}%"] if section else [])
    try:
        df = con.execute(
            f"SELECT * FROM (SELECT passage_id, section, heading, text, "
            f"fts_main_{table}.match_bm25(passage_id, ?) AS score FROM \"{table}\") "
            f"{where} ORDER BY score DESC LIMIT {int(k)}", params).df()
    except duckdb.Error:   # no full-text index: count keyword hits instead
        df = con.execute(f'SELECT passage_id, section, heading, text FROM "{table}"').df()
        if section:
            df = df[df["section"].str.contains(section, case=False, regex=False)]
        stems = [t[:5] for t in _terms(query)]
        df["score"] = df["text"].str.lower().map(lambda s: sum(s.count(t) for t in stems))
        df = df[df["score"] > 0].nlargest(k, "score")
    terms = _terms(query)
    df["text"] = [trim(t, terms) for t in df["text"]]
    return df.drop(columns="score").reset_index(drop=True)
