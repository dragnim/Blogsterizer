from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.linkcheck import check_links, summarise
from app.session import build_session
from app.version import __version__
from app.engine import analyse_html, plain_text_to_html
from app.fetcher import FetchError, fetch_html
from app.profiles import DEFAULT_PROFILE_ID, ProfileError, load_profile


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="The Blogsterizer",
    description="Deterministic HTML clean-up and editorial reporting.",
    version=__version__,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["version"] = __version__


class AnalysePayload(BaseModel):
    source_type: str = Field(pattern="^(html|text|url)$")
    content: str = Field(min_length=1)
    selector: str | None = None


def _resolve_source(source_type: str, content: str, selector: str | None = None) -> str:
    if source_type == "html":
        return content
    if source_type == "text":
        return plain_text_to_html(content)
    if source_type == "url":
        return fetch_html(content.strip(), selector.strip() if selector else None)
    raise ValueError("Unsupported source type.")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={},
    )


@app.post("/analyse", response_class=HTMLResponse)
async def analyse_form(
    request: Request,
    source_type: str = Form(...),
    content: str = Form(...),
    selector: str = Form(""),
):
    try:
        source_html = _resolve_source(source_type, content, selector)
        profile = load_profile(DEFAULT_PROFILE_ID)
        session = build_session(source_html, profile)
    except (FetchError, ProfileError, ValueError) as exc:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": str(exc),
                "source_type": source_type,
                "content": content,
                "selector": selector,
            },
            status_code=400,
        )

    return templates.TemplateResponse(
        request=request,
        name="results.html",
        context={
            "result": session,
            "source": source_html,
            "history": [],
        },
    )


@app.post("/api/analyse")
async def analyse_api(payload: AnalysePayload):
    try:
        source_html = _resolve_source(payload.source_type, payload.content, payload.selector)
        profile = load_profile(DEFAULT_PROFILE_ID)
        result = analyse_html(source_html, profile)
    except (FetchError, ProfileError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result.to_dict())


@app.post("/apply", response_class=HTMLResponse)
async def apply_suggestion(
    request: Request,
    source: str = Form(...),
    history: str = Form("[]"),
    action: str = Form(...),
    params: str = Form("{}"),
    value: str = Form(""),
):
    """Record one chosen fix and rebuild the whole session from the source."""
    try:
        entries = json.loads(history or "[]")
        arguments = json.loads(params or "{}")
    except json.JSONDecodeError:
        # Malformed form state: show the analysis rather than a server error.
        session = build_session(source, load_profile(DEFAULT_PROFILE_ID))
        return templates.TemplateResponse(
            request=request,
            name="results.html",
            context={
                "result": session,
                "source": source,
                "history": [],
                "action_error": "That change could not be read. The analysis has been reloaded.",
            },
        )

    if value:
        arguments["value"] = value
    entries.append({"action": action, "params": arguments})

    session = build_session(source, load_profile(DEFAULT_PROFILE_ID), entries)

    # If the new fix would not apply, drop it and say why rather than losing work.
    notice = None
    if len(session.fixes) < len(entries):
        entries = entries[:len(session.fixes)]
        session = build_session(source, load_profile(DEFAULT_PROFILE_ID), entries)
        session.error = session.error or "That change could not be applied."
    elif session.fixes:
        notice = session.fixes[-1].message

    return templates.TemplateResponse(
        request=request,
        name="results.html",
        context={
            "result": session,
            "source": source,
            "history": entries,
            "notice": notice,
            "action_error": session.error,
        },
    )


@app.post("/undo", response_class=HTMLResponse)
async def undo_fix(
    request: Request,
    source: str = Form(...),
    history: str = Form("[]"),
    index: int = Form(-1),
):
    """Remove one fix and replay the rest.

    Any fix can be removed, not just the most recent. A later fix was recorded
    against the document as it stood *after* this one, so removing an earlier
    fix can leave a later one unable to replay; build_session reports that
    rather than dropping it quietly.
    """
    try:
        entries = json.loads(history or "[]")
    except json.JSONDecodeError:
        entries = []

    if not entries:
        undone = None
    elif 0 <= index < len(entries):
        undone = entries.pop(index)
    else:
        undone = entries.pop()
    session = build_session(source, load_profile(DEFAULT_PROFILE_ID), entries)
    return templates.TemplateResponse(
        request=request,
        name="results.html",
        context={
            "result": session,
            "source": source,
            "history": entries,
            "notice": "Undid the last change." if undone else None,
            "action_error": session.error,
        },
    )


@app.post("/check-links", response_class=HTMLResponse)
async def check_document_links(
    request: Request,
    source: str = Form(...),
    history: str = Form("[]"),
):
    """Check the links in the current document. Requests the network, on demand.

    Deliberately separate from /analyse: the rules are deterministic and offline,
    this is neither, and mixing them would make the findings depend on whether a
    remote site happened to answer.
    """
    try:
        entries = json.loads(history or "[]")
    except json.JSONDecodeError:
        entries = []

    session = build_session(source, load_profile(DEFAULT_PROFILE_ID), entries)
    results = await check_links(session.cleaned_html)

    return templates.TemplateResponse(
        request=request,
        name="results.html",
        context={
            "result": session,
            "source": source,
            "history": entries,
            "link_results": results,
            "link_summary": summarise(results),
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok", "app": "The Blogsterizer", "version": __version__}
