"""Single-company views that need no AI: snapshot figures, readable statements, starter questions."""

import re
import string

import duckdb
import pandas as pd

import financial_ratios as fr

STATEMENT_TITLES = {"income_statement": "Income statement",
                    "balance_sheet": "Balance sheet",
                    "cash_flow": "Cash flow"}


def snapshot(con: duckdb.DuckDBPyConnection, prefix: str) -> dict:
    """Key figures for the latest fiscal year, the year before, and the yearly history."""
    values, _ = fr.inputs(con, prefix)
    ratios, _ = fr.compute(con, prefix)
    years = sorted(values.get("revenue", {}))
    if not years:
        return {}
    latest = years[-1]
    prior = years[-2] if len(years) > 1 else None

    def pick(key, source, year):
        if year is None:
            return None
        if source == "value":
            return values.get(key, {}).get(year)
        return ratios.loc[key, year] if key in ratios.index and year in ratios.columns else None

    metrics = [  # (label, key, source, kind)
        ("Revenue", "revenue", "value", "money"),
        ("Net income", "net_income", "value", "money"),
        ("Net margin", "net_margin", "ratio", "pct"),
        ("Free cash flow", "free_cash_flow", "value", "money"),
        ("Return on equity", "roe", "ratio", "pct"),
    ]
    cards = []
    for label, key, source, kind in metrics:
        now, before = pick(key, source, latest), pick(key, source, prior)
        if now is None or pd.isna(now):
            continue
        cards.append({"label": label, "value": now, "previous": None if before is None or pd.isna(before) else before,
                      "kind": kind})
    history = pd.DataFrame({
        "fiscal_year": years,
        "Revenue": [values["revenue"].get(y) for y in years],
        "Net income": [values.get("net_income", {}).get(y) for y in years],
    })
    return {"year": latest, "prior_year": prior, "cards": cards, "history": history}


LEDGER_LINES = [  # (label, key, source, kind) - the key lines shown across the years
    ("Revenue", "revenue", "value", "money"),
    ("Operating income", "operating_income", "value", "money"),
    ("Net income", "net_income", "value", "money"),
    ("Net margin", "net_margin", "ratio", "pct"),
    ("Free cash flow", "free_cash_flow", "value", "money"),
    ("Return on equity", "roe", "ratio", "pct"),
]


def ledger(con: duckdb.DuckDBPyConnection, prefix: str) -> dict:
    """Key lines × fiscal years (money in $ millions, ratios in %), for the ledger strip."""
    values, _ = fr.inputs(con, prefix)
    ratios, _ = fr.compute(con, prefix)
    years = sorted(values.get("revenue", {}))
    lines = []
    for label, key, source, kind in LEDGER_LINES:
        if source == "value":
            series = values.get(key, {})
        else:
            series = ratios.loc[key].dropna().to_dict() if key in ratios.index else {}
        row = {str(y): float(series[y]) for y in years if y in series and pd.notna(series[y])}
        if row:
            lines.append({"label": label, "kind": kind, "values": row})
    return {"years": [str(y) for y in years], "lines": lines}


def statement_rows(con: duckdb.DuckDBPyConnection, table: str, show_segments: bool = False) -> dict:
    """Statement as structured rows for the web UI: headings, indented items, values per year."""
    df = con.execute(f'SELECT * FROM "{table}"').df()
    if not show_segments:
        df = df[df["segment"].isna()]
    if df.empty:
        return {"years": [], "rows": []}
    df = df.assign(segment=df["segment"].astype(object).where(df["segment"].notna(), ""),
                   section=df["section"].astype(object).where(df["section"].notna(), ""))
    wide = (df.pivot_table(index=["line_order", "segment", "section", "line_item"], columns="fiscal_year",
                           values="value", aggfunc="first")
              .sort_index(level="line_order"))
    years = sorted(wide.columns, reverse=True)
    rows, current = [], None
    for (_, segment, section, item), vals in wide[years].iterrows():
        heading = " › ".join(filter(None, [segment, section]))
        if heading != current and heading:
            rows.append({"label": heading, "heading": True, "indent": False, "values": {}})
        current = heading
        rows.append({"label": item, "heading": False, "indent": bool(heading),
                     "total": item.lower().startswith("total"),
                     "values": {str(y): float(vals[y]) for y in years if pd.notna(vals[y])}})
    return {"years": [str(y) for y in years], "rows": rows}


def statement_table(con: duckdb.DuckDBPyConnection, table: str, show_segments: bool = False) -> pd.DataFrame:
    """A statement laid out like the annual report: line items as rows, years as columns
    (newest first), section headings as their own rows."""
    df = con.execute(f'SELECT * FROM "{table}"').df()
    if not show_segments:
        df = df[df["segment"].isna()]
    if df.empty:
        return pd.DataFrame()
    df = df.assign(segment=df["segment"].astype(object).where(df["segment"].notna(), ""),
                   section=df["section"].astype(object).where(df["section"].notna(), ""))
    wide = (df.pivot_table(index=["line_order", "segment", "section", "line_item"], columns="fiscal_year",
                           values="value", aggfunc="first")
              .sort_index(level="line_order"))
    years = sorted(wide.columns, reverse=True)
    rows, current = [], None
    for (_, segment, section, item), values in wide[years].iterrows():
        heading = " › ".join(filter(None, [segment, section]))
        if heading != current and heading:
            rows.append({"Line item": heading.upper(), **{str(y): None for y in years}})
        current = heading
        rows.append({"Line item": ("    " if heading else "") + item,
                     **{str(y): values[y] for y in years}})
    return pd.DataFrame(rows)


def units_note(con: duckdb.DuckDBPyConnection, table: str) -> str:
    units = [u for (u,) in con.execute(
        f'SELECT units FROM "{table}" WHERE units IS NOT NULL GROUP BY units ORDER BY COUNT(*) DESC').fetchall()]
    if not units:
        return ""
    exceptions = ["per-share figures" if u == "per share" else f"share counts (in {u.replace(' of shares', '')})"
                  for u in units[1:]]
    return f"Values in $ {units[0]}" + (f", except {' and '.join(exceptions)}." if exceptions else ".")


def display_name(name: str) -> str:
    """SEC often stores names in capitals: 'COCA COLA CO' → 'Coca Cola Co' (keeps "McDonald's" right),
    and some end in a state-of-registration tag like '/DE/', which is dropped."""
    name = re.sub(r"\s*/[A-Za-z]{2,3}/?\s*$", "", name).strip()
    return string.capwords(name.lower()) if name.isupper() else name


def short_name(name: str) -> str:
    """'MICROSOFT CORP' → 'Microsoft', 'Apple Inc.' → 'Apple'."""
    if name.isupper():
        name = name.title()
    previous = None
    while previous != name:
        previous = name
        name = re.sub(r"[,.]?\s+(inc|corp|corporation|co|company|ltd|plc|holdings|&)\.?$", "", name.strip(),
                      flags=re.I)
    return name


def starter_questions(con: duckdb.DuckDBPyConnection, prefix: str, name: str) -> list[str]:
    """Example questions tailored to what this company's data contains."""
    short = short_name(name)
    questions = [f"How have {short}'s revenue and net income changed over the years?",
                 f"What are {short}'s profit margins, and are they improving?",
                 f"How much free cash flow does {short} generate? Show a chart."]
    # Revenue broken down by segment or by section (e.g. Apple's Products / Services)?
    _, used = fr.inputs(con, prefix)
    revenue_label = used.get("revenue")
    has_breakdown = bool(revenue_label) and con.execute(  # revenue label used in more than one place
        f'SELECT COUNT(DISTINCT (COALESCE(segment, \'\'), COALESCE(section, \'\'))) '
        f'FROM "{prefix}_income_statement" WHERE line_item = ?', [revenue_label]).fetchone()[0] > 1
    questions.append(f"Break down {short}'s revenue by business line." if has_breakdown
                     else f"How strong is {short}'s balance sheet?")
    # A "why" question when the filing's MD&A was read (answered with quotes via search_filing)
    tables = {n for (n,) in con.execute("SHOW TABLES").fetchall()}
    if f"{prefix}_filing_text" in tables and con.execute(
            f'SELECT COUNT(*) FROM "{prefix}_filing_text" WHERE section = \'MD&A\'').fetchone()[0]:
        questions.append(f"What does management say drove {short}'s revenue growth?")
    return questions
