"""Yoast focus keyphrase and meta description.

Drafted by a model, checked against the post, never written into the HTML. The
checks matter: a keyphrase the post never uses will score green in Yoast while
the page ranks for nothing, and that is detectable rather than something to
take on trust.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.postseo import PostSEO, check, draft_post_seo, post_text

POST = (
    "<h2>Evaluating APL</h2>"
    "<p>With tool calling in an agent, we can give an LLM the ability to evaluate APL. "
    "The simplest route is the dyalogscript CLI, which has shipped with Dyalog since "
    "version 19.0. Teaching Claude Code how to use dyalogscript is remarkably simple. "
    "Enabling APL evaluation unlocks a lot of APL ability in the latest models, and this "
    "post walks through the working practices and container set-up that make it "
    "practical to use an AI coding agent with Dyalog APL day to day.</p>"
)


def stub(reply: str, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"content": [{"type": "text", "text": reply}]})

    return httpx.Client(transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------------
# Without a key
# --------------------------------------------------------------------------

def test_without_a_key_nothing_is_invented(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    draft = draft_post_seo(POST)
    assert draft.status == "TODO"
    assert draft.keyphrase == ""
    assert draft.meta == ""
    assert ".env" in draft.detail


def test_too_little_text_is_refused(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    draft = draft_post_seo("<p>Short.</p>")
    assert draft.status == "TODO"
    assert "too little text" in draft.detail


# --------------------------------------------------------------------------
# Drafting
# --------------------------------------------------------------------------

def test_a_draft_is_marked_unreviewed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = stub(
        "KEYPHRASE: dyalogscript CLI\n"
        "META: How to give an AI coding agent the ability to evaluate Dyalog APL, using the "
        "dyalogscript CLI and a container.\n"
        "TITLE: SAME"
    )
    draft = draft_post_seo(POST, client=client)
    assert draft.status == "UNREVIEWED"
    assert draft.keyphrase == "dyalogscript CLI"
    assert draft.meta.startswith("How to give")
    # TITLE: SAME means the existing heading is fine.
    assert draft.title == ""


def test_an_api_error_does_not_lose_the_run(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    draft = draft_post_seo(POST, client=stub("", status=529))
    assert draft.status == "FAILED"
    assert "529" in draft.detail


def test_an_unusable_reply_is_reported(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    draft = draft_post_seo(POST, client=stub("I'm afraid I can't help with that."))
    assert draft.status == "FAILED"


# --------------------------------------------------------------------------
# Checking the draft against the post
# --------------------------------------------------------------------------

def test_a_keyphrase_the_post_never_uses_is_flagged():
    text = post_text(POST)
    draft = check(PostSEO(keyphrase="quantum blockchain", meta="x" * 130), text)
    assert any("not used in the post" in warning for warning in draft.warnings)


def test_a_keyphrase_the_post_does_use_is_not_flagged():
    text = post_text(POST)
    draft = check(PostSEO(keyphrase="dyalogscript CLI", meta="x" * 130), text)
    assert not any("not used" in warning for warning in draft.warnings)


def test_a_short_meta_description_is_flagged():
    draft = check(PostSEO(keyphrase="dyalogscript", meta="Too short."), post_text(POST))
    assert any("120-155" in warning for warning in draft.warnings)


def test_a_long_meta_description_is_flagged():
    draft = check(PostSEO(keyphrase="dyalogscript", meta="x" * 200), post_text(POST))
    assert any("truncated" in warning for warning in draft.warnings)


def test_a_meta_description_in_range_is_not_flagged():
    draft = check(PostSEO(keyphrase="dyalogscript", meta="x" * 140), post_text(POST))
    assert draft.warnings == []


def test_a_long_seo_title_is_flagged():
    draft = check(
        PostSEO(keyphrase="dyalogscript", meta="x" * 130, title="y" * 80), post_text(POST)
    )
    assert any("under 60" in warning for warning in draft.warnings)


# --------------------------------------------------------------------------
# Nothing reaches the HTML
# --------------------------------------------------------------------------

def test_drafting_does_not_change_the_document(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = TestClient(app)
    response = client.post("/seo-draft", data={"source": POST, "history": "[]"})
    assert response.status_code == 200
    # The keyphrase and meta are fields to paste into Yoast, not content: no
    # description meta tag is injected. (The page's own charset and viewport
    # tags are the app's chrome, not the post's.)
    assert '<meta name="description"' not in response.text
    assert "<meta property=" not in response.text
    assert "Evaluating APL" in response.text


def test_the_panel_offers_the_draft_without_running_it():
    client = TestClient(app)
    page = client.post(
        "/analyse", data={"source_type": "html", "content": POST, "selector": ""}
    ).text
    assert 'data-tab="seo"' in page
    assert "Draft Yoast fields" in page
    assert 'class="seo-draft"' not in page  # nothing drafted yet


def test_post_text_strips_markup_and_normalises_space():
    text = post_text("<h2>Title</h2>\n\n<p>Some   text  here.</p>")
    assert text == "Title Some text here."
