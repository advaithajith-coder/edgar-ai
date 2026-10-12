"""LangChain data-analysis agent: Groq LLM + DuckDB SQL tools + Plotly charts."""

import difflib
import re
import time
from dataclasses import dataclass, field
from typing import Callable

import duckdb
import groq
import pandas as pd
import plotly.express as px
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq

import filing_text
import financial_ratios as fr

MAX_ROWS_TO_LLM = 30          # keep tool output small (Groq free tier has low token limits)
# Different companies label the same thing differently ("Revenue" vs "Net sales")
SYNONYMS = {
    "revenue": ("sales", "revenues"), "revenues": ("sales", "revenue"), "sales": ("revenue", "revenues"),
    "profit": ("income", "earnings"), "income": ("earnings",), "earnings": ("income",),
    "capex": ("property", "equipment"), "debt": ("borrowings", "notes"),
}
READ_ONLY = re.compile(r"^\s*(select|with|describe|summarize|show|pragma\s+table_info)\b", re.I)

SYSTEM_PROMPT = """You are EDGAR.AI, an expert data analyst working with a DuckDB database of companies'
annual reports (10-K filings from SEC EDGAR). If asked who you are, introduce yourself as EDGAR.AI.

How to work:
0. For standard ratios - gross/operating/net margin, revenue or net income growth, ROE, ROA,
   current ratio, debt-to-equity, free cash flow, FCF margin - call `financial_ratios` directly
   (no list_tables or SQL needed; one call can cover several companies and ratios). To chart
   them, call create_chart with SQL on the `ratios` table it creates.
1. If you don't already know the schema, call `list_tables` first.
   For financial statement tables, then call `find_line_items` ONCE for all the tables you
   need (comma-separated), with search keywords for the items in the question, e.g.
   tables="aapl_income_statement, msft_income_statement", search="revenue|sales|net income".
   Use the exact line_item names it returns - never guess them.
2. Answer questions by writing DuckDB SQL and running it with `run_sql`. Never guess numbers -
   every figure in your answer must come from a tool result you have actually seen.
3. When a chart would help (trends, comparisons, distributions) or the user asks for one,
   call `create_chart`. Aggregate in SQL first so the chart has a sensible number of points.
4. Quote identifiers with double quotes if they could clash with SQL keywords.
5. If a query fails, read the error, fix the SQL, and try again.

Financial statement tables (columns line_order, segment, section, line_item, period, fiscal_year, value, units):
- One row per line item per year. Filter with the exact line_item text from `find_line_items`.
- Rows with a non-NULL `segment` are breakdowns (business lines, consolidated VIEs, ...).
  For company-wide figures always add `segment IS NULL`; use segment rows only when asked
  about a breakdown.
- The same line_item can appear in several sections (e.g. "Net sales" overall vs. under
  "Products"/"Services"). The company-wide total is usually the row whose section IS NULL -
  always filter on section too, and never SUM duplicate line items.
- Respect `units` (e.g. millions). Per-share and share-count rows use different units.
- Other ratios (not covered by financial_ratios): divide line items for the same fiscal_year,
  pivoting with conditional aggregation: MAX(value) FILTER (WHERE line_item = '...').
- Growth: use LAG(value) OVER (ORDER BY fiscal_year). Negative numbers are outflows/expenses.
- Balance sheet items are point-in-time; income and cash-flow items cover the whole year.
- Tables loaded from SEC are named <ticker>_income_statement / _balance_sheet / _cash_flow and
  have a `company` column. To compare companies, UNION ALL their tables. Companies use different
  labels for the same thing (e.g. "Net sales" vs "Revenue" vs "Revenues"), so search broadly
  (e.g. "revenue|sales") and use each company's own label.
- Companies have different fiscal year-ends and filing dates, so their latest years may differ
  (e.g. one has 2026 data, another only up to 2025). Only compare the same fiscal_year, and say
  so when a company has no data for a year.

Follow-up questions:
- The previous answer may come with a note listing the queries it used and describing the
  `last_result` table (the data behind that answer). For follow-ups like "just 2025",
  "chart that", "sort by…", "and Microsoft?", reuse `last_result` or adapt those queries
  instead of starting from scratch.

Questions the data can't answer:
- Only use the loaded tables. If a question needs something they don't contain - stock
  prices, market share, forecasts, news, analyst views, quarterly figures, years or companies
  that aren't loaded - say clearly what's missing, then offer the closest thing you CAN
  answer from the data. If a company isn't loaded, say it can be loaded with its ticker in
  the "Load a company" box in the sidebar (the app looks at one company at a time).
- For "why", risk or strategy questions: get the numbers first, then call `search_filing` once or
  twice for management's explanation, and quote it briefly with its section, e.g. (MD&A). Only
  give reasons the filing states; if the search finds none, say the filing doesn't explain it.
  Never fill gaps with general knowledge or guesses. Don't search for plain number questions.

Final answer: lead with the direct answer, then any key numbers or a small markdown table,
then one or two short insights if they are useful. Insights must be backed by numbers you
have queried - don't claim a trend or "compared with prior years" unless you fetched those
years too. Be concise. Don't paste SQL in the answer -
the app shows it separately. Charts appear automatically below your answer, so never write
image links or markdown images for them.

End every answer with one last line in exactly this format, with 2-3 short follow-up
questions that the loaded data can answer:
Suggestions: <question 1> | <question 2> | <question 3>"""


@dataclass
class TurnTrace:
    """What the agent did during one user question (shown in the UI)."""
    queries: list[str] = field(default_factory=list)
    figures: list = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)   # filing passages quoted by search_filing
    last_result: str = ""   # description of the `last_result` table, for follow-up questions


SUGGESTIONS_LINE = re.compile(r"^\W*suggestions?\W*:\W*(.+)$", re.I | re.M)


MEMORY_TURNS = 6  # past Q&A pairs sent back to the model (keeps Groq token usage low)


def message_text(msg) -> str:
    """Final answer text, without fake image links (charts are shown separately)."""
    return re.sub(r"!\[[^\]]*\]\([^)]*\)\n?", "", msg.text)


def conversation(turns: list[dict], question: str) -> list:
    """Recent Q&A for the model. Only the latest answer carries its follow-up note (queries used
    and what's in `last_result`), since `last_result` always holds the latest answer's data."""
    messages = []
    recent = turns[-MEMORY_TURNS:]
    for i, turn in enumerate(recent):
        answer = turn["answer"]
        if i == len(recent) - 1 and turn.get("context"):
            answer += f"\n\n[Note for follow-ups: {turn['context']}]"
        messages += [HumanMessage(turn["question"]), AIMessage(answer)]
    return messages + [HumanMessage(question)]


def follow_up_note(trace: "TurnTrace") -> str:
    if not trace.queries:
        return ""
    queries = "\n".join(trace.queries)
    if len(queries) > 1500:
        queries = queries[:1500] + " …"
    note = f"queries used:\n{queries}"
    if trace.last_result:
        note += f"\nThe final result is saved as table last_result: {trace.last_result}"
    return note


def split_suggestions(answer: str) -> tuple[str, list[str]]:
    """Separate the 'Suggestions: q1 | q2 | q3' line from the answer text."""
    match = SUGGESTIONS_LINE.search(answer)
    if not match:
        return answer.strip(), []
    questions = [q.strip(" *_`") for q in match.group(1).split("|")]
    return (answer[:match.start()] + answer[match.end():]).strip(), [q for q in questions if len(q) > 3][:3]


def _run(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    if not READ_ONLY.match(sql):
        raise ValueError("Only read-only queries (SELECT / WITH / DESCRIBE / SUMMARIZE) are allowed.")
    df = con.execute(sql).df()
    return df if df is not None else pd.DataFrame()


TEXT_SUFFIX = "_filing_text"   # tables of written 10-K passages (see filing_text.py)
SCRATCH_TABLES = {"last_result": "data behind the previous answer",
                  "ratios": "output of the last financial_ratios call"}


def build_tools(con: duckdb.DuckDBPyConnection, trace: TurnTrace):
    """Create tools bound to this database connection and this turn's trace."""

    def save_result(df: pd.DataFrame, source: str = ""):
        """Keep a result as a table so follow-up questions can reuse it."""
        con.register("last_result", df)
        trace.last_result = f"{len(df)} rows; columns: {list(df.columns)}" + (f" (from {source})" if source else "")

    def financial_tables() -> list[str]:
        return [n for (n,) in con.execute(
            "SELECT DISTINCT table_name FROM information_schema.columns WHERE column_name = 'line_item'"
        ).fetchall()]

    @tool
    def list_tables() -> str:
        """Short overview of every table. For financial statement tables, get the exact
        line item names afterwards with `find_line_items`."""
        fin = set(financial_tables())
        out = []
        if fin:
            out.append("Financial statement tables (columns: company, line_order, segment, section, "
                       "line_item, period, fiscal_year, value, units):")
        for (name,) in con.execute("SHOW TABLES").fetchall():
            if name in SCRATCH_TABLES:
                continue
            if name.endswith(TEXT_SUFFIX):   # just say it's there; samples would cost tokens
                out.append(f"- {name}: written 10-K passages, search with `search_filing`")
                continue
            rows = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            if name in fin:
                years, items, seg_items = con.execute(
                    f'SELECT string_agg(DISTINCT fiscal_year::VARCHAR, \', \' ORDER BY fiscal_year::VARCHAR), '
                    f'COUNT(DISTINCT line_item) FILTER (WHERE segment IS NULL), '
                    f'COUNT(DISTINCT segment) FROM "{name}"').fetchone()
                out.append(f"- {name}: fiscal years {years}; {items} line items"
                           + (f" + breakdowns for {seg_items} segments" if seg_items else ""))
            else:
                cols = con.execute(f'DESCRIBE "{name}"').df()[["column_name", "column_type"]]
                sample = con.execute(f'SELECT * FROM "{name}" LIMIT 3').df()
                out.append(f"## {name} ({rows} rows)\nColumns: "
                           + ", ".join(f"{c} ({t})" for c, t in cols.itertuples(index=False))
                           + f"\nSample:\n{sample.to_markdown(index=False)}")
        scratch = [n for (n,) in con.execute("SHOW TABLES").fetchall() if n in SCRATCH_TABLES]
        if scratch:
            out.append("Also available: " + "; ".join(f"{n} ({SCRATCH_TABLES[n]})" for n in scratch))
        return "\n".join(out) or "No tables loaded."

    @tool
    def find_line_items(tables: str, search: str = "") -> str:
        """Get the exact line_item names (with segment and section) of financial statement tables.

        Args:
            tables: One or more table names, comma-separated, e.g. "aapl_income_statement, msft_income_statement".
            search: Optional keywords separated by "|", e.g. "revenue|sales|net income". Empty returns
                every company-wide line item and just the names of breakdown segments.
        """
        fin = set(financial_tables())
        keywords = [k.strip().lower() for k in re.split(r"[|,]", search) if k.strip()]
        out = []
        for name in [t.strip().strip('"') for t in tables.split(",") if t.strip()]:
            if name not in fin:
                out.append(f"## {name}: not a financial statement table. Available: {sorted(fin)}")
                continue
            rows = con.execute(
                f'SELECT segment, section, line_item, ANY_VALUE(units), MIN(line_order) o FROM "{name}" '
                f'GROUP BY segment, section, line_item ORDER BY o').fetchall()
            lines, segments = [], {}
            for segment, section, item, units, _ in rows:
                text = " ".join(filter(None, [segment, section, item])).lower()
                if keywords and not any(k in text for k in keywords):
                    continue
                if segment and not keywords:
                    segments[segment] = segments.get(segment, 0) + 1
                    continue
                label = (f"[segment: {segment}] " if segment else "") + (f"{section} > " if section else "") + item
                lines.append(label + (f"  ({units})" if units and units != "millions" else ""))
            text = f"## {name} (values in millions unless noted)\n" + ("\n".join(lines) or "No matching line items.")
            if segments:
                text += "\nBreakdown segments (search to see their items): " + ", ".join(
                    f"{s} ({n})" for s, n in segments.items())
            out.append(text)
        return "\n\n".join(out)

    @tool
    def financial_ratios(companies: str, ratios: str = "") -> str:
        """Calculate standard financial ratios for one or more companies, for every available year.
        Use this instead of writing SQL for these ratios. Results are also saved to the table
        `ratios` (company, ratio, fiscal_year, value) so they can be charted with create_chart.

        Args:
            companies: Comma-separated company prefixes, e.g. "aapl, msft" (the part before
                _income_statement in the table names).
            ratios: Comma-separated ratio names, or empty for all: gross_margin, operating_margin,
                net_margin, revenue_growth, net_income_growth, roe, roa, current_ratio,
                debt_to_equity, free_cash_flow, fcf_margin.
        """
        available = fr.company_prefixes(con)
        wanted = [r.strip() for r in ratios.split(",") if r.strip()] or list(fr.RATIOS)
        unknown = [r for r in wanted if r not in fr.RATIOS]
        if unknown:
            return f"Unknown ratios {unknown}. Available: {list(fr.RATIOS)}"
        out, rows, notes = [], [], []
        for prefix in [c.strip().lower() for c in companies.split(",") if c.strip()]:
            if prefix not in available:
                out.append(f"'{prefix}': no statement tables found. Available companies: {available}")
                continue
            table, used = fr.compute(con, prefix)
            table = table.reindex([r for r in wanted if r in table.index]).dropna(how="all")
            for ratio, series in table.iterrows():
                rows += [{"company": prefix.upper(), "ratio": ratio, "fiscal_year": int(y), "value": round(v, 2)}
                         for y, v in series.items() if pd.notna(v)]
            shown = table.map(lambda v: "" if pd.isna(v) else f"{v:,.2f}")
            shown.columns = [str(c) for c in shown.columns]
            missing = [r for r in wanted if r not in table.index]
            relevant = {k for r in wanted for k in fr.NEEDS[r]}
            inputs = "; ".join(f"{k} = '{v}'" for k, v in used.items() if k in relevant)
            out.append(f"## {prefix.upper()}\n{shown.to_markdown()}\n"
                       + (f"Not available (missing inputs): {missing}\n" if missing else "")
                       + f"Line items used: {inputs}")
            notes.append(f"-- {prefix.upper()} inputs: {inputs}")
        if rows:
            con.register("ratios", pd.DataFrame(rows))
            save_result(pd.DataFrame(rows), source="financial_ratios")
        trace.queries.append(f"-- financial_ratios(companies='{companies}', ratios='{ratios or 'all'}')\n"
                             + "\n".join(notes))
        definitions = "\n".join(f"- {r}: {fr.RATIOS[r]}" for r in wanted)
        return "\n\n".join(out) + f"\n\nDefinitions:\n{definitions}"

    def line_item_hint(query: str) -> str:
        """If a query used line item names that don't exist, suggest the closest real ones."""
        literals = {m.replace("''", "'") for m in re.findall(r"'((?:[^']|'')+)'", query)}
        hints = []
        for name in financial_tables():
            if not re.search(rf"\b{re.escape(name)}\b", query, re.I):
                continue
            known = {v for row in con.execute(
                f'SELECT DISTINCT line_item, section, segment, company FROM "{name}"').fetchall()
                for v in row if v}
            main_items = [i for (i,) in con.execute(
                f'SELECT line_item FROM "{name}" WHERE segment IS NULL '
                f'GROUP BY line_item ORDER BY MIN(line_order)').fetchall()]
            for lit in sorted(literals - known):
                if len(lit) < 3 or lit.isdigit():
                    continue
                words = {w for w in re.findall(r"[a-z]+", lit.lower())}
                words |= {s for w in words for s in SYNONYMS.get(w, ())}
                overlap = {i: len(words & set(re.findall(r"[a-z]+", i.lower()))) for i in main_items
                           if not i.lower().startswith(("cost", "total cost"))}
                close = [i for i in sorted(overlap, key=overlap.get, reverse=True) if overlap[i]][:4] \
                    or difflib.get_close_matches(lit, main_items, n=3, cutoff=0.6)
                hint = f"'{lit}' is not a line_item in {name}."
                hints.append(hint + (f" Did you mean: {close}?" if close else
                                     f" Company-wide line items: {main_items}"))
        return ("\n" + "\n".join(hints)) if hints else ""

    @tool
    def run_sql(query: str) -> str:
        """Run a read-only DuckDB SQL query and return the result as a markdown table.

        Args:
            query: A DuckDB SELECT / WITH / DESCRIBE / SUMMARIZE statement.
        """
        trace.queries.append(query)
        try:
            df = _run(con, query)
        except Exception as e:
            return f"SQL error: {e}"
        if df.empty:
            return "Query returned 0 rows." + line_item_hint(query)
        save_result(df)
        shown = df.head(MAX_ROWS_TO_LLM).to_markdown(index=False)
        if len(df) > MAX_ROWS_TO_LLM:
            shown += f"\n\n(Showing first {MAX_ROWS_TO_LLM} of {len(df)} rows. Aggregate or add LIMIT for a smaller result.)"
        return shown

    @tool
    def create_chart(query: str, chart_type: str, x: str, y: str,
                     color: str = "", title: str = "") -> str:
        """Run a SQL query and draw a chart of the result for the user.

        Args:
            query: Read-only DuckDB SQL whose result contains the columns to plot.
            chart_type: One of "bar", "line", "scatter", "pie", "histogram", "box", "area".
            x: Result column for the x-axis (for pie: the category/labels column).
            y: Result column for the y-axis (for pie: the values column; for histogram: may equal x).
            color: Optional result column used to split series by colour. Empty string for none.
            title: Short chart title.
        """
        trace.queries.append(query)
        try:
            df = _run(con, query)
        except Exception as e:
            return f"SQL error: {e}"
        if df.empty:
            return "Query returned 0 rows, nothing to plot." + line_item_hint(query)
        missing = [c for c in (x, y, color) if c and c not in df.columns]
        if missing:
            return f"Columns {missing} not in result. Available: {list(df.columns)}"

        color = color or None
        kind = chart_type.lower()
        try:
            if kind == "pie":
                fig = px.pie(df, names=x, values=y, title=title)
            elif kind == "histogram":
                fig = px.histogram(df, x=x, color=color, title=title)
            elif kind in ("bar", "line", "scatter", "box", "area"):
                fig = getattr(px, kind)(df, x=x, y=y, color=color, title=title)
            else:
                return f"Unknown chart_type '{chart_type}'."
        except Exception as e:
            return f"Chart error: {e}"

        trace.figures.append(fig)
        save_result(df)
        # Return the plotted data so the model can quote real numbers instead of guessing
        data = df.head(MAX_ROWS_TO_LLM).to_markdown(index=False)
        return f"Chart '{title}' displayed to the user ({len(df)} data points). Plotted data:\n{data}"

    @tool
    def search_filing(query: str, section: str = "") -> str:
        """Search the 10-K's written sections for management's explanations, risks and plans.

        Args:
            query: Keywords, e.g. "cloud revenue growth Azure".
            section: Optional: "MD&A", "Risk factors" or "Market risk".
        """
        tables = [n for (n,) in con.execute("SHOW TABLES").fetchall() if n.endswith(TEXT_SUFFIX)]
        if not tables:
            return "The written sections of this 10-K couldn't be read; only the statements are available."
        out = []
        for table in tables:
            company = table[: -len(TEXT_SUFFIX)].upper()
            for p in filing_text.search(con, table, query, section).itertuples():
                where = p.section + (f" > {p.heading}" if p.heading else "")
                source = {"company": company, "section": p.section, "heading": p.heading, "text": p.text}
                if source not in trace.sources:
                    trace.sources.append(source)
                out.append(f"[{company}, {where}] {p.text}")
        return "\n\n".join(out) or "No passage matches. Try other keywords, or say the filing doesn't explain it."

    return [list_tables, find_line_items, financial_ratios, run_sql, create_chart, search_filing]


MAX_WAITS = 3            # retries per model call before giving up
MAX_WAIT_SECONDS = 60


def _retry_after(error: Exception, attempt: int) -> float:
    """Seconds to wait: Groq's retry-after header if present, else exponential backoff."""
    response = getattr(error, "response", None)
    try:
        wait = float(response.headers.get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        wait = 5 * 2 ** attempt
    return min(max(wait, 1.0), MAX_WAIT_SECONDS)


def _is_daily_limit(error: Exception) -> bool:
    return bool(re.search(r"per day|\b(RPD|TPD)\b", str(error)))


def wait_and_retry(on_wait: Callable[[int, int, str], None] | None = None):
    """Middleware: when Groq is rate-limited or briefly unavailable, wait and retry the same
    model call (the agent keeps its progress) instead of failing the whole question."""

    @wrap_model_call
    def retry_on_rate_limit(request, handler):
        for attempt in range(MAX_WAITS + 1):
            try:
                return handler(request)
            except (groq.RateLimitError, groq.APIConnectionError, groq.APITimeoutError,
                    groq.InternalServerError) as e:
                if attempt == MAX_WAITS or _is_daily_limit(e):
                    raise
                reason = "Groq rate limit reached" if isinstance(e, groq.RateLimitError) else "Groq is busy"
                wait = _retry_after(e, attempt)
                for remaining in range(int(round(wait)), 0, -1):  # countdown, 1 s at a time
                    if on_wait:
                        on_wait(remaining, attempt + 1, reason)
                    time.sleep(1)

    return retry_on_rate_limit


def friendly_error(error: Exception) -> str:
    """Plain-English explanation of an error from Groq or the agent."""
    text = str(error)
    if isinstance(error, groq.AuthenticationError):
        return "The Groq API key in `.env` was rejected. Check that it's correct and still active."
    if isinstance(error, groq.RateLimitError):
        when = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", text)
        if _is_daily_limit(error):
            wait = ""
            if when and any(when.groups()):
                h, m, s = (float(g) if g else 0 for g in when.groups())
                wait = " ".join(f"{int(v)} {u}" for v, u in ((h, "h"), (m, "min"), (s, "s")) if int(v))
            return ("You've reached Groq's daily free-tier limit. It frees up gradually over the day"
                    + (f", so try again in about {wait}." if wait else ", so try again later."))
        return "Groq's free-tier limit is still busy after several retries. Wait a minute and ask again."
    if isinstance(error, groq.APIStatusError) and error.status_code == 413:
        return ("This question needs more data than Groq's free tier allows in one request. "
                "Try fewer companies or a narrower question.")
    if isinstance(error, (groq.APIConnectionError, groq.APITimeoutError)):
        return "Couldn't reach Groq. Check your internet connection and try again."
    if isinstance(error, groq.InternalServerError):
        return "Groq is having problems right now. Try again in a minute."
    return f"Something went wrong: `{text[:300]}`. Try rephrasing the question."


def build_agent(con: duckdb.DuckDBPyConnection, api_key: str, model: str, trace: TurnTrace,
                on_wait: Callable[[int, int, str], None] | None = None):
    # max_retries=0: the middleware does the retrying, so the app can show what's happening
    llm = ChatGroq(model=model, api_key=api_key, temperature=0, max_retries=0)
    return create_agent(llm, tools=build_tools(con, trace), system_prompt=SYSTEM_PROMPT,
                        middleware=[wait_and_retry(on_wait)])
