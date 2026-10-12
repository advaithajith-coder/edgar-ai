"""FastAPI backend for the React front end. Reuses the agent, SEC loader, ratios and company view.

Run:  uvicorn server:app --port 8010
(After `npm run build` in frontend/, this also serves the web app at http://localhost:8010.)
"""

import json
import os
import queue
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage
from pydantic import BaseModel

import company_view as cv
from agent import (MAX_WAITS, TurnTrace, build_agent, conversation, follow_up_note, friendly_error,
                   message_text, split_suggestions)
from data_loader import build_database
from sec_fetcher import SecError, company_list, fetch_company, search_companies

load_dotenv()
API_KEY = os.getenv("GROQ_API_KEY", "")
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
SEC_CACHE_SECONDS = 24 * 3600

app = FastAPI(title="AI Data Analyst")

# One workspace per browser tab (the front end sends a random X-Session id). Demo-scale: in memory.
SESSIONS: dict[str, dict] = {}
SEC_CACHE: dict[str, tuple[float, tuple]] = {}
TOOL_LABELS = {
    "list_tables": "Looking at the data",
    "find_line_items": "Finding the right line items",
    "financial_ratios": "Calculating ratios",
    "run_sql": "Running a query",
    "create_chart": "Drawing a chart",
    "search_filing": "Reading the filing",
}


def session(session_id: str | None) -> dict:
    if not session_id:
        raise HTTPException(400, "Missing X-Session header.")
    return SESSIONS.setdefault(session_id, {"company": None, "con": None, "turns": []})


def rebuild(s: dict):
    """Rebuild the database from the loaded company's statements, and start a fresh chat."""
    s["con"] = build_database(s["company"]["tables"]) if s["company"] else None
    s["turns"] = []


def fetch_cached(ticker: str):
    hit = SEC_CACHE.get(ticker)
    if hit and time.time() - hit[0] < SEC_CACHE_SECONDS:
        return hit[1]
    data = fetch_company(ticker)
    SEC_CACHE[ticker] = (time.time(), data)
    return data


def company_payload(s: dict) -> dict | None:
    c = s["company"]
    if not c:
        return None
    info, prefix, con = c["info"], c["prefix"], s["con"]
    return {
        "ticker": c["ticker"], "name": cv.display_name(info["name"]), "shortName": cv.short_name(info["name"]),
        "period": info["period"], "filed": info["filed"], "url": info["url"],
        "ledger": cv.ledger(con, prefix),
        "starters": cv.starter_questions(con, prefix, info["name"]),
        "statements": [{"key": k, "title": t} for k, t in cv.STATEMENT_TITLES.items()],
    }


# ---------------------------------------------------------------- workspace
@app.get("/api/workspace")
def workspace(x_session: str | None = Header(None)):
    s = session(x_session)
    return {"company": company_payload(s), "hasKey": bool(API_KEY),
            "turns": [{k: t.get(k, []) for k in ("question", "answer", "suggestions", "steps", "figures", "sources")}
                      for t in s["turns"]]}


class CompanyRequest(BaseModel):
    ticker: str


POPULAR = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "JPM", "KO", "WMT", "NFLX", "COST"]


@app.get("/api/companies")
def companies(q: str = ""):
    """Company picker: matches for the typed text, or popular companies when it's empty."""
    try:
        if q.strip():
            found = search_companies(q)
        else:
            by_ticker = {c["ticker"]: c for c in company_list()}
            found = [by_ticker[t] for t in POPULAR if t in by_ticker]
    except Exception as e:
        raise HTTPException(502, f"Couldn't reach SEC EDGAR ({e}). Check your internet connection.")
    return [{"ticker": c["ticker"], "name": cv.display_name(c["name"])} for c in found]


@app.post("/api/company")
def load_company(req: CompanyRequest, x_session: str | None = Header(None)):
    s = session(x_session)
    ticker = req.ticker.strip().upper()
    if not ticker:
        raise HTTPException(400, "Type a ticker, for example AAPL.")
    try:
        tables, info = fetch_cached(ticker)
    except SecError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"Couldn't reach SEC EDGAR ({e}). Check your internet connection.")
    prefix = next(n[: -len("_income_statement")] for n in tables if n.endswith("_income_statement"))
    s["company"] = {"ticker": ticker, "tables": tables, "info": info, "prefix": prefix}
    rebuild(s)
    return company_payload(s)


@app.delete("/api/company")
def remove_company(x_session: str | None = Header(None)):
    s = session(x_session)
    s["company"] = None
    rebuild(s)
    return {"ok": True}


@app.get("/api/statement/{key}")
def statement(key: str, segments: bool = False, x_session: str | None = Header(None)):
    s = session(x_session)
    if not s["company"] or key not in cv.STATEMENT_TITLES:
        raise HTTPException(404, "No company loaded.")
    table = f"{s['company']['prefix']}_{key}"
    return {**cv.statement_rows(s["con"], table, segments), "unitsNote": cv.units_note(s["con"], table)}


# ---------------------------------------------------------------- chat
class AskRequest(BaseModel):
    question: str


@app.post("/api/clear")
def clear_chat(x_session: str | None = Header(None)):
    session(x_session)["turns"] = []
    return {"ok": True}


@app.post("/api/ask")
def ask(req: AskRequest, x_session: str | None = Header(None)):
    """Stream the agent's progress as newline-delimited JSON events:
    {"type": "status"|"wait"|"answer", ...}."""
    s = session(x_session)
    question = req.question.strip()
    if not question:
        raise HTTPException(400, "Type a question first.")
    if s["con"] is None:
        raise HTTPException(400, "Load a company first.")
    if not API_KEY:
        raise HTTPException(500, "GROQ_API_KEY is missing from .env, so the agent can't answer yet.")

    events: queue.Queue = queue.Queue()
    trace = TurnTrace()

    def on_wait(seconds_left: int, attempt: int, reason: str):
        events.put({"type": "wait", "seconds": seconds_left, "attempt": attempt, "of": MAX_WAITS,
                    "reason": reason})

    def run():
        answer, error = "", False
        try:
            agent = build_agent(s["con"], API_KEY, MODEL, trace, on_wait=on_wait)
            for update in agent.stream({"messages": conversation(s["turns"], question)}, stream_mode="updates"):
                for payload in update.values():
                    for msg in (payload or {}).get("messages", []):
                        if isinstance(msg, AIMessage):
                            for call in msg.tool_calls:
                                events.put({"type": "status", "text": TOOL_LABELS.get(call["name"], call["name"])})
                            if not msg.tool_calls and message_text(msg):
                                answer = message_text(msg)
        except Exception as e:
            answer, error = friendly_error(e), True
        answer, suggestions = split_suggestions(answer) if not error else (answer, [])
        turn = {"question": question, "answer": answer or "No answer came back. Try asking again.",
                "suggestions": suggestions, "steps": trace.queries,
                "figures": [json.loads(f.to_json()) for f in trace.figures],
                "sources": trace.sources,
                "context": follow_up_note(trace), "error": error}
        if not error:
            s["turns"].append(turn)
        events.put({"type": "answer", **{k: v for k, v in turn.items() if k != "context"}})
        events.put(None)

    threading.Thread(target=run, daemon=True).start()

    def stream():
        while (event := events.get()) is not None:
            yield json.dumps(event) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# ---------------------------------------------------------------- web app (after `npm run build`)
DIST = Path(__file__).parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def web_app(path: str):
        """Files in dist/ as-is; any other page address (/, /report) gets the app, which routes itself."""
        file = (DIST / path).resolve()
        if path and file.is_file() and DIST.resolve() in file.parents:
            return FileResponse(file)
        if path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        # no-cache: browsers re-check the page, so a new build shows up without a hard refresh
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
