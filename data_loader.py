"""Turn SEC statement pages into long-format tables and load them into DuckDB.

A statement (line items as rows, periods as columns, title rows on top, negatives written
as "(1,234)") is reshaped into one row per line item per period:
  line_order, segment, section, line_item, period, fiscal_year, value [, units]
"""

import re

import duckdb
import pandas as pd

from filing_text import index_passages

MAX_HEADER_SCAN = 15  # rows to search for the real header row


def parse_numbers(series: pd.Series) -> pd.Series:
    """Text → numbers: "1,234", "$ 5.00", "12%", "(321)" → -321. Unparseable → NaN."""
    s = series.astype(str).str.strip()
    negative = s.str.contains(r"\(\s*[\d.,]+\s*\)", regex=True)  # accounting negatives, e.g. "$ (1,234)"
    s = s.str.replace(r"[(),$€£₹%\s]", "", regex=True)
    numbers = pd.to_numeric(s, errors="coerce")
    return numbers.where(~negative, -numbers)


def parse_period(header) -> tuple[str, int] | None:
    """Recognise a period column header: "Sep. 27, 2025", "FY2024", "2023", "Mar 2024"."""
    text = str(header).strip()
    year = re.search(r"\b(19|20)\d{2}\b", text)
    if not year:
        return None
    if re.fullmatch(r"(FY\s*'?)?(19|20)\d{2}", text, flags=re.I):
        return text, int(year.group(0))
    try:
        date = pd.to_datetime(text.replace(".", ""), errors="raise")
        return date.strftime("%Y-%m-%d"), date.year
    except (ValueError, TypeError):
        return None


def split_header(raw: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Find the real header row (skipping titles above it). Returns (data, title_text)."""
    raw = raw.dropna(how="all").dropna(axis=1, how="all")
    if raw.empty:
        return raw, ""
    top = raw.head(MAX_HEADER_SCAN)
    filled = top.notna().sum(axis=1)
    header_pos = int((filled >= filled.max()).to_numpy().argmax())  # first "full" row

    title = " ".join(str(v) for v in top.iloc[:header_pos].stack().tolist())
    header = raw.iloc[header_pos].tolist()
    data = raw.iloc[header_pos + 1:].reset_index(drop=True)
    data.columns = [str(h).strip() if pd.notna(h) else f"column_{i + 1}" for i, h in enumerate(header)]
    return data, title


# ---------------------------------------------------------------- financial statements
def statement_periods(df: pd.DataFrame) -> dict[str, tuple[str, int]] | None:
    """If df looks like a financial statement, return {column: (period, year)}."""
    if df.shape[1] < 2:
        return None
    periods = {c: p for c in df.columns[1:] if (p := parse_period(c))}
    if len(periods) < 1 or len(periods) < 0.6 * (df.shape[1] - 1):
        return None
    first = df.iloc[:, 0]
    if parse_numbers(first).notna().mean() > 0.5:  # first column must be labels, not numbers
        return None
    values = pd.concat([parse_numbers(df[c]) for c in periods], axis=1)
    filled = df[list(periods)].notna()
    if values.notna().sum().sum() < 0.8 * filled.sum().sum():
        return None
    return periods


def statement_to_long(df: pd.DataFrame, periods: dict, title: str) -> pd.DataFrame:
    """Reshape line items × periods into one row per (line_item, period)."""
    scale = r"(thousands|millions|billions|crores?|lakhs?)"
    shares = re.search(rf"shares in {scale}", title, re.I)
    money = re.search(rf"(?<!shares )\bin {scale}", title, re.I)  # e.g. "$ in Millions", "₹ in Crores"
    money_units = money.group(1).lower() if money else None

    def units_for(label: str, section: str | None) -> str | None:
        low, sec = label.lower(), (section or "").lower()
        # Share counts: "Basic (in shares)", or under "Shares used in…" / "Weighted average shares outstanding"
        if ("(in shares)" in low or low.startswith("shares")
                or re.search(r"^shares|shares (used|outstanding)|average shares", sec)):
            scale_word = shares.group(1).lower() if shares else money_units  # "In Millions, except per share"
            return f"{scale_word} of shares" if scale_word else "shares"
        # EPS / dividends per share - but "$0.001 par value per share" lines are dollar amounts
        if "par value" not in low and ("per share" in low or "per share" in sec):
            return "per share"
        return money_units

    label_col = df.columns[0]
    numbers = {c: parse_numbers(df[c]) for c in periods}

    # Pass 1: assign each data row a section, and split the statement into blocks.
    # A new block starts where 2+ heading rows are stacked after data, e.g. Tesla's
    # "Automotive sales" / "Revenues" or JPMorgan's "VIEs consolidated by the Firm" / "Assets".
    blocks: list[dict] = [{"group": None, "items": []}]
    section, run, seen_data = None, [], False
    for i in range(len(df)):
        label = df[label_col].iloc[i]
        if pd.isna(label):
            continue
        label = str(label).strip()
        if "[abstract]" in label.lower() or re.match(r"^\[\d+\]", label):  # XBRL markers, footnotes
            continue
        vals = {c: numbers[c].iloc[i] for c in periods}
        if all(pd.isna(v) for v in vals.values()):
            run.append(label.rstrip(":").strip())  # heading row like "Operating activities:"
            continue
        if run:
            if len(run) >= 2 and seen_data:
                blocks.append({"group": run[0], "items": []})
            section, run = run[-1], []
        seen_data = True
        blocks[-1]["items"].append((i, label, section, vals))
        # A "Total ..." / "Cash generated by ..." row closes the current section
        if re.match(r"(total\b|cash (generated|used|provided))", label, re.I):
            section = None

    # Pass 2: a block is a breakdown (segment / business line / VIE), not part of the
    # company-wide statement, if SEC labels it as an XBRL "[Member]" or it mostly repeats
    # line items already seen above it.
    rows, seen_items = [], set()
    for block in blocks:
        group = block["group"]
        labels = {label for _, label, _, _ in block["items"]}
        is_breakdown = group is not None and (
            "[member]" in group.lower() or len(labels & seen_items) >= 0.5 * len(labels))
        seen_items |= labels
        segment = re.sub(r"\s*\[member\]", "", group, flags=re.I) if is_breakdown else None
        for i, label, sec, vals in block["items"]:
            for col, v in vals.items():
                if pd.notna(v):
                    period, year = periods[col]
                    rows.append({"line_order": i + 1,
                                 "segment": segment,
                                 "section": sec, "line_item": label,
                                 "period": period, "fiscal_year": year, "value": float(v),
                                 "units": units_for(label, sec)})

    long = pd.DataFrame(rows)
    if long.empty:
        return long
    # Always text, even when empty (an all-empty column would otherwise become a number column)
    for col in ("segment", "section", "units"):
        long[col] = long[col].astype("string")
    if long["units"].isna().all():
        long = long.drop(columns="units")
    return long


# ---------------------------------------------------------------- public API
def process_raw(raw: pd.DataFrame) -> pd.DataFrame:
    """Raw statement page (no header) → long-format statement, or empty if it isn't one."""
    data, title = split_header(raw)
    if data.empty:
        return data
    periods = statement_periods(data)
    return statement_to_long(data, periods, title) if periods else pd.DataFrame()


def build_database(tables: dict[str, pd.DataFrame]) -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB database with one table per statement (plus the filing's
    written passages, which get a full-text index)."""
    con = duckdb.connect(database=":memory:")
    for name, df in tables.items():
        con.register(f"_df_{name}", df)
        con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM "_df_{name}"')
        con.unregister(f"_df_{name}")
        if name.endswith("_filing_text"):
            index_passages(con, name)
    return con
