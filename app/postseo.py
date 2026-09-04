"""Draft a Yoast focus keyphrase and meta description for a post.

Same rules as the image alt text (handoff section 26): the model drafts, a human
decides. Nothing here is written into the HTML — a meta description and a focus
keyphrase are fields you paste into Yoast, not content — and every draft is
marked as unreviewed.

The post's own words are sent, not a summary, because a keyphrase has to be a
phrase the post actually uses. A keyphrase the post never says is worse than
none: Yoast will score it green while the page ranks for nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup

from app.imagetext import API_URL, API_VERSION, MODEL, TIMEOUT, api_key


# Enough of the post for the model to judge what it is about, without sending
# the whole thing when it runs long.
MAX_CHARS = 12000

PROMPT = """Below is the text of a Dyalog APL technical blog post.

<post>
{text}
</post>

Produce three things for the site's Yoast SEO fields.

1. KEYPHRASE: the focus keyphrase, 2-5 words. It MUST be a phrase that appears in the post, or a very close variant of one. Prefer what a reader would actually search for. Do not invent a phrase the post does not use.
2. META: a meta description, 120-155 characters, describing what the reader will get from the post. Active voice. No clickbait, no "in this blog post". It must be accurate to the post's actual content.
3. TITLE: an SEO title under 60 characters, if the post's own heading is longer or less clear than it could be. If the existing heading is already fine, write SAME.

Reply with exactly three lines:
KEYPHRASE: ...
META: ...
TITLE: ..."""


@dataclass
class PostSEO:
    keyphrase: str = ""
    meta: str = ""
    title: str = ""
    status: str = "TODO"  # UNREVIEWED | TODO | FAILED
    detail: str = ""
    warnings: list[str] = field(default_factory=list)


def post_text(html: str) -> str:
    """The readable text of the post, for judging what it is about."""
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style"]):
        element.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)[:MAX_CHARS]


def _parse(reply: str) -> PostSEO:
    fields = {"KEYPHRASE": "", "META": "", "TITLE": ""}
    for line in reply.splitlines():
        for key in fields:
            if line.strip().upper().startswith(f"{key}:"):
                fields[key] = line.split(":", 1)[1].strip()
    if not fields["KEYPHRASE"] and not fields["META"]:
        return PostSEO(status="FAILED", detail="No usable fields in the reply.")
    title = "" if fields["TITLE"].upper() == "SAME" else fields["TITLE"]
    return PostSEO(
        keyphrase=fields["KEYPHRASE"],
        meta=fields["META"],
        title=title,
        status="UNREVIEWED",
    )


def check(draft: PostSEO, text: str) -> PostSEO:
    """Sanity-check the draft against the post itself.

    A model will occasionally produce a keyphrase the post never uses, or a meta
    description outside the length Yoast wants. Both are checkable, so they are
    checked rather than trusted.
    """
    warnings: list[str] = []
    lowered = text.lower()

    if draft.keyphrase and draft.keyphrase.lower() not in lowered:
        words = [word for word in re.findall(r"[a-z0-9]+", draft.keyphrase.lower())]
        missing = [word for word in words if word not in lowered]
        if missing:
            warnings.append(
                f"The keyphrase is not used in the post (missing: {', '.join(missing)}). "
                "Yoast will score it green while the page ranks for nothing."
            )
        else:
            warnings.append(
                "The keyphrase does not appear as a phrase in the post, though its "
                "individual words do. Check it reads naturally."
            )

    if draft.meta:
        length = len(draft.meta)
        if length < 120:
            warnings.append(f"The meta description is {length} characters; Yoast wants 120-155.")
        elif length > 155:
            warnings.append(
                f"The meta description is {length} characters and will be truncated in "
                "search results; Yoast wants 120-155."
            )

    if draft.title and len(draft.title) > 60:
        warnings.append(f"The SEO title is {len(draft.title)} characters; keep it under 60.")

    draft.warnings = warnings
    return draft


def draft_post_seo(html: str, client: httpx.Client | None = None) -> PostSEO:
    """Draft the Yoast fields for a post. Never raises."""
    key = api_key()
    if not key:
        return PostSEO(
            status="TODO",
            detail=(
                "No ANTHROPIC_API_KEY is set, so nothing was drafted. Put the key in a "
                ".env file beside pyproject.toml, or in the environment, and restart."
            ),
        )

    text = post_text(html)
    if len(text) < 200:
        return PostSEO(
            status="TODO",
            detail="There is too little text here to judge what the post is about.",
        )

    owns_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT)
    try:
        response = client.post(
            API_URL,
            headers={
                "x-api-key": key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 400,
                "messages": [{"role": "user", "content": PROMPT.format(text=text)}],
            },
        )
    except httpx.HTTPError as exc:
        return PostSEO(status="FAILED", detail=f"Request failed: {type(exc).__name__}.")
    finally:
        if owns_client:
            client.close()

    if response.status_code != 200:
        return PostSEO(status="FAILED", detail=f"The API answered {response.status_code}.")

    try:
        blocks = response.json().get("content", [])
        reply = "\n".join(
            block.get("text", "") for block in blocks if block.get("type") == "text"
        )
    except ValueError:
        return PostSEO(status="FAILED", detail="Could not read the API reply.")

    return check(_parse(reply), text)
