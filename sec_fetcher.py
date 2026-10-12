"""Fetch a company's financial statements from its latest 10-K on SEC EDGAR.

Flow: ticker → CIK (company_tickers.json) → latest 10-K (submissions API)
      → FilingSummary.xml (which R*.htm page is which statement)
      → R*.htm statement pages → long-format tables (data_loader.process_raw).
      The main 10-K document also gives the written sections as passages (filing_text).
"""

import os
import re
import xml.etree.ElementTree as ET
from io import StringIO

import pandas as pd
import requests

import filing_text
from data_loader import parse_numbers, process_raw

# SEC asks automated tools to identify themselves: "AppName contact@example.com".
# Set SEC_USER_AGENT in .env to your own name/email.
USER_AGENT = os.getenv("SEC_USER_AGENT", "DataAnalysisAgent/1.0 personal-project admin@localhost.test")

STATEMENTS = {
    # table suffix: (patterns the statement's name must match, patterns it must not match)
    "income_statement": (r"operations|income|earnings", r"comprehensive|parenthetical"),
    "balance_sheet": (r"balance sheet|financial position|financial condition", r"parenthetical"),
    "cash_flow": (r"cash flow", r"parenthetical"),
}


class SecError(Exception):
    """A user-facing problem fetching SEC data (unknown ticker, no 10-K, ...)."""


def _get(url: str) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    if r.status_code == 404:
        raise SecError(f"Not found on SEC: {url}")
    r.raise_for_status()
    return r


_COMPANY_LIST: list[dict] = []


def company_list() -> list[dict]:
    """Every ticker SEC knows: [{'ticker', 'name', 'cik'}], downloaded once. A company with
    several share classes (e.g. BRK-A, BRK-B) appears once per ticker, main class first."""
    if not _COMPANY_LIST:
        data = _get("https://www.sec.gov/files/company_tickers.json").json()
        _COMPANY_LIST.extend({"ticker": row["ticker"].upper(), "name": row["title"], "cik": row["cik_str"]}
                             for row in data.values())
    return _COMPANY_LIST


def search_companies(query: str, limit: int = 12) -> list[dict]:
    """Match by ticker first (exact, then prefix), then by words in the company name.
    Name matches show each company once (its main share class)."""
    q = query.strip().lower()
    if not q:
        return []
    exact, prefix, name_start, name_has = [], [], [], []
    named = set()
    for c in company_list():
        if c["ticker"].lower() not in (q,) and not c["ticker"].lower().startswith(q):
            if c["cik"] in named:
                continue
            named.add(c["cik"])
        ticker, name = c["ticker"].lower(), c["name"].lower()
        if ticker == q:
            exact.append(c)
        elif ticker.startswith(q):
            prefix.append(c)
        elif name.startswith(q) or f" {q}" in f" {name}":
            name_start.append(c)
        elif q in name or (" " in q and q.replace(" ", "") in name.replace(" ", "")):  # "jp morgan" → JPMORGAN
            name_has.append(c)
    return (exact + sorted(prefix, key=lambda c: len(c["ticker"])) + name_start + name_has)[:limit]


def lookup_company(ticker: str) -> tuple[int, str]:
    """Return (CIK, company name) for a ticker like 'AAPL', or a numeric CIK like '34088'."""
    if ticker.isdigit():
        cik = int(ticker)
        return cik, _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()["name"]
    for c in company_list():
        if c["ticker"] == ticker.upper():
            return int(c["cik"]), c["name"]
    raise SecError(f"Ticker '{ticker}' not found on SEC EDGAR.")


def latest_10k(cik: int, name: str = "") -> dict:
    """Return {'accession', 'filed', 'period', 'document'} for the company's most recent 10-K."""
    recent = _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()["filings"]["recent"]
    forms = set(recent["form"])
    for form, acc, filed, period, document in zip(recent["form"], recent["accessionNumber"], recent["filingDate"],
                                                  recent["reportDate"], recent["primaryDocument"]):
        if form == "10-K":
            return {"accession": acc, "filed": filed, "period": period, "document": document}
    who = f"{name} (CIK {cik})" if name else f"CIK {cik}"
    if forms & {"20-F", "40-F"}:
        raise SecError(f"{who} is a foreign filer (20-F/40-F reports), which isn't supported.")
    raise SecError(f"{who} has no 10-K on file. If the company recently reorganised, its reports may be "
                   "under an older entity - search its name on sec.gov/edgar and enter that CIK number instead.")


def find_statement_pages(base_url: str) -> dict[str, tuple[str, str]]:
    """Map our statement names to (R page file, statement title) using FilingSummary.xml."""
    root = ET.fromstring(_get(f"{base_url}/FilingSummary.xml").content)
    reports = [
        (r.findtext("HtmlFileName"), r.findtext("LongName") or "", r.findtext("ShortName") or "")
        for r in root.iter("Report")
        if r.findtext("HtmlFileName")
    ]
    pages = {}
    for key, (include, exclude) in STATEMENTS.items():
        for html, long_name, short_name in reports:
            # Primary statements are labelled "... - Statement - NAME"
            if " - statement - " not in long_name.lower():
                continue
            if re.search(include, short_name, re.I) and not re.search(exclude, short_name, re.I):
                pages[key] = (html, short_name)
                break
    return pages


def read_statement_page(url: str) -> pd.DataFrame:
    """Turn an SEC R*.htm statement page into a raw sheet: title row, header row, data rows."""
    table = pd.read_html(StringIO(_get(url).text))[0]
    cols = table.columns
    if isinstance(cols, pd.MultiIndex):
        title, periods = cols[0][0], [c[-1] for c in cols[1:]]
    else:
        title, periods = cols[0], list(cols[1:])
    header = ["Line item"] + periods
    rows = [[title] + [None] * len(periods), header] + table.astype(object).values.tolist()
    raw = pd.DataFrame(rows)
    # Drop footnote-marker columns (they only hold "[1]" etc., never numbers)
    keep = [0] + [c for c in raw.columns[1:] if parse_numbers(raw[c].iloc[2:]).notna().any()]
    raw = raw[keep]
    raw.columns = range(len(keep))
    return raw


def fetch_company(ticker: str) -> tuple[dict[str, pd.DataFrame], dict]:
    """Return ({table_name: long-format statement}, info) for the ticker's latest 10-K."""
    cik, name = lookup_company(ticker)
    filing = latest_10k(cik, name)
    base_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{filing['accession'].replace('-', '')}"
    pages = find_statement_pages(base_url)
    if not pages:
        raise SecError(f"Couldn't find financial statements in {name}'s 10-K.")

    prefix = re.sub(r"[^a-z0-9]+", "_", ticker.lower())
    if prefix[0].isdigit():
        prefix = f"cik{prefix}"  # table names must not start with a digit
    tables = {}
    for key, (html, _) in pages.items():
        df = process_raw(read_statement_page(f"{base_url}/{html}"))
        if df.empty or "line_item" not in df.columns:
            continue
        df.insert(0, "company", ticker.upper())
        tables[f"{prefix}_{key}"] = df

    # The written sections are a bonus: if the document can't be read, the company still loads.
    try:
        text = filing_text.filing_passages(_get(f"{base_url}/{filing['document']}").content)
        if not text.empty:
            tables[f"{prefix}_filing_text"] = text
    except Exception:
        pass

    info = {"ticker": ticker.upper(), "name": name, "filed": filing["filed"],
            "period": filing["period"], "statements": sorted(pages),
            "url": f"{base_url}/{filing['accession']}-index.htm"}
    return tables, info
