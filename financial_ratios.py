"""Standard financial ratios computed from the long-format statement tables.

Companies label the same thing differently ("Net sales" / "Revenue" / "Revenues"), so each
building block (revenue, net income, equity, ...) is found with an ordered list of label
patterns. Only company-wide rows are used (segment IS NULL). Every result reports which
line items it used, so answers can be checked.
"""

import re

import duckdb
import pandas as pd

STATEMENTS = ("income_statement", "balance_sheet", "cash_flow")

# metric: (statement, [regex patterns, most preferred first], [patterns to exclude])
NOT_NCI = r"(?!.*non-?controlling)"
HOLDERS = r"(stockholders|shareholders|shareowners)"
INPUTS = {
    "revenue": ("income_statement", [
        r"^total net (sales|revenues?)$", r"^total revenues?$", r"^net (sales|revenues?)$",
        r"^(total )?net operating revenues?$", r"^revenues?$", r"^total net revenue$", r"^sales$",
    ], []),
    "gross_profit": ("income_statement", [r"^(total )?gross (margin|profit)$"], []),
    "cost_of_revenue": ("income_statement", [
        r"^total cost of (revenues?|sales)$", r"^cost of (revenues?|sales)$"], []),
    "operating_income": ("income_statement", [
        r"^(total )?operating income( \(loss\))?$", r"^income( \(loss\))? from operations$",
        r"^operating (profit|loss)$"], []),
    "net_income": ("income_statement", [
        rf"^(consolidated )?net (income|earnings)( \(loss\))? attributable to {NOT_NCI}.*",
        r"^net (income|earnings)( \(loss\))?$"], [r"per share", r"including non-?controlling"]),
    "total_assets": ("balance_sheet", [r"^total assets$"], []),
    "total_liabilities": ("balance_sheet", [r"^total liabilities$"], []),
    "current_assets": ("balance_sheet", [r"^total current assets$"], []),
    "current_liabilities": ("balance_sheet", [r"^total current liabilities$"], []),
    # Equity of the company's own shareholders (excluding minority/noncontrolling owners)
    "equity": ("balance_sheet", [
        rf"^total (?!{HOLDERS}){NOT_NCI}.+ {HOLDERS}[’']? equity$",   # "Total Walmart shareholders' equity"
        rf"^equity attributable to (?!non)",                          # "Equity attributable to shareowners of …"
        r"share of equity$",                                          # "ExxonMobil share of equity"
        rf"^(?!total){NOT_NCI}.+ {HOLDERS}[’']? equity$",             # "Berkshire shareholders' equity"
        rf"^total {HOLDERS}[’']? equity$",                            # "Total shareholders' equity"
        r"^total equity$"],
        [r"liabilities and", r"non-?controlling", r"including"]),
    "operating_cash_flow": ("cash_flow", [
        r"^(net )?cash (generated|provided|from).*operat(ing activities|ions)$",
        r"^net cash .*operating activities$"], [r"discontinued"]),
    "capex": ("cash_flow", [
        r"^(purchases? (of|related to)|payments for( acquisition of)?|additions to|acquisitions? of) "
        r"property(,)? (plant,? )?and equipment",
        r"^capital expenditures"], []),
}
# Debt is summed from several balance-sheet lines (short-term + long-term parts)
DEBT_PATTERN = (r"^(total debt|long-term debt|short-term debt|term debt|commercial paper|"
                r"current portion of long-term debt|short-term borrowings|long-term borrowings|"
                r"notes payable and other borrowings)\b")

RATIOS = {
    "gross_margin": "Gross margin % = gross profit / revenue × 100",
    "operating_margin": "Operating margin % = operating income / revenue × 100",
    "net_margin": "Net margin % = net income / revenue × 100",
    "revenue_growth": "Revenue growth % vs. prior year",
    "net_income_growth": "Net income growth % vs. prior year",
    "roe": "Return on equity % = net income / year-end equity × 100",
    "roa": "Return on assets % = net income / year-end total assets × 100",
    "current_ratio": "Current ratio = current assets / current liabilities",
    "debt_to_equity": "Debt-to-equity = total debt / equity",
    "free_cash_flow": "Free cash flow ($ millions) = operating cash flow − capital expenditures",
    "fcf_margin": "FCF margin % = free cash flow / revenue × 100",
}


# Which building blocks each ratio uses (to report only the relevant line items)
NEEDS = {
    "gross_margin": ["gross_profit", "revenue"], "operating_margin": ["operating_income", "revenue"],
    "net_margin": ["net_income", "revenue"], "revenue_growth": ["revenue"],
    "net_income_growth": ["net_income"], "roe": ["net_income", "equity"],
    "roa": ["net_income", "total_assets"], "current_ratio": ["current_assets", "current_liabilities"],
    "debt_to_equity": ["debt", "equity"], "free_cash_flow": ["operating_cash_flow", "capex"],
    "fcf_margin": ["operating_cash_flow", "capex", "revenue"],
}


def company_prefixes(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Table prefixes that have statement tables, e.g. 'aapl' for aapl_income_statement."""
    names = [n for (n,) in con.execute("SHOW TABLES").fetchall()]
    return sorted({n[: -len(s) - 1] for n in names for s in STATEMENTS if n.endswith("_" + s)})


def _matches(labels: pd.Series, pattern: str) -> pd.Series:
    regex = re.compile(pattern, re.I)
    return labels.map(lambda label: bool(regex.search(label)))


def _label(row) -> str:
    section = row["section"]
    return (f"{section} > " if isinstance(section, str) and section else "") + row["line_item"]


def _find(df: pd.DataFrame, patterns: list[str], exclude: list[str]) -> pd.DataFrame | None:
    """First pattern that matches a company-wide line item → that item's rows (one per year)."""
    main = df[df["segment"].isna()]
    labels = main["line_item"].astype(str).str.strip()
    for pattern in patterns:
        hit = _matches(labels, pattern)
        for ex in exclude:
            hit &= ~_matches(labels, ex)
        if hit.any():
            # Several rows can share a label (e.g. under different sections); prefer section-less
            # rows, then the first occurrence in the statement.
            rows = main[hit].assign(_section=main["section"].astype(object).where(main["section"].notna(), ""))
            rows = rows.sort_values(["_section", "line_order"], key=lambda c: c.ne("") if c.name == "_section" else c)
            first = rows.iloc[0]
            same = rows[(rows["line_item"] == first["line_item"]) & (rows["_section"] == first["_section"])]
            return same.drop_duplicates("fiscal_year")
    return None


def inputs(con: duckdb.DuckDBPyConnection, prefix: str) -> tuple[dict[str, dict[int, float]], dict[str, str]]:
    """Find the building blocks: ({input: {fiscal_year: value}}, {input: line item used})."""
    tables = {}
    for s in STATEMENTS:
        name = f"{prefix}_{s}"
        try:
            tables[s] = con.execute(f'SELECT * FROM "{name}"').df()
        except duckdb.Error:
            tables[s] = pd.DataFrame(columns=["segment", "section", "line_item", "fiscal_year", "value", "line_order"])

    values: dict[str, dict[int, float]] = {}
    used: dict[str, str] = {}
    for key, (statement, patterns, exclude) in INPUTS.items():
        rows = _find(tables[statement], patterns, exclude)
        if rows is not None:
            values[key] = dict(zip(rows["fiscal_year"], rows["value"]))
            used[key] = rows.iloc[0]["line_item"]

    # Debt: sum the matching balance-sheet lines (or use "Total debt" alone if present)
    bs = tables["balance_sheet"]
    if not bs.empty:
        debt_rows = bs[bs["segment"].isna() & _matches(bs["line_item"].astype(str), DEBT_PATTERN)]
        if debt_rows["line_item"].str.lower().str.startswith("total debt").any():
            debt_rows = debt_rows[debt_rows["line_item"].str.lower().str.startswith("total debt")]
        if not debt_rows.empty:
            values["debt"] = debt_rows.groupby("fiscal_year")["value"].sum().to_dict()
            used["debt"] = " + ".join(dict.fromkeys(_label(r) for _, r in debt_rows.iterrows()))

    # Gross profit = revenue − cost of revenue when the company doesn't report it directly
    if "gross_profit" not in values and "revenue" in values and "cost_of_revenue" in values:
        values["gross_profit"] = {y: values["revenue"][y] - abs(c)
                                  for y, c in values["cost_of_revenue"].items() if y in values["revenue"]}
        used["gross_profit"] = f"{used['revenue']} − {used['cost_of_revenue']}"

    values["free_cash_flow"] = {y: ocf - abs(values["capex"][y])
                                for y, ocf in values.get("operating_cash_flow", {}).items()
                                if y in values.get("capex", {})}
    return values, used


def compute(con: duckdb.DuckDBPyConnection, prefix: str) -> tuple[pd.DataFrame, dict[str, str]]:
    """Return (ratios table: ratio × fiscal_year, {input: line item used})."""
    values, used = inputs(con, prefix)

    def ratio(num, den, scale=100.0):
        a, b = values.get(num, {}), values.get(den, {})
        return {y: scale * a[y] / b[y] for y in a if y in b and b[y]}

    def growth(key):
        v = values.get(key, {})
        return {y: 100 * (v[y] / v[y - 1] - 1) for y in v if y - 1 in v and v[y - 1]}

    results = {
        "gross_margin": ratio("gross_profit", "revenue"),
        "operating_margin": ratio("operating_income", "revenue"),
        "net_margin": ratio("net_income", "revenue"),
        "revenue_growth": growth("revenue"),
        "net_income_growth": growth("net_income"),
        "roe": ratio("net_income", "equity"),
        "roa": ratio("net_income", "total_assets"),
        "current_ratio": ratio("current_assets", "current_liabilities", 1.0),
        "debt_to_equity": ratio("debt", "equity", 1.0),
        "free_cash_flow": values["free_cash_flow"],
        "fcf_margin": ratio("free_cash_flow", "revenue"),
    }
    table = pd.DataFrame(results).T
    table = table.reindex(sorted(table.columns), axis=1) if not table.empty else table
    return table, used
