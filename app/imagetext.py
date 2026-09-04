"""Draft alt text and titles for processed images.

Section 26 of the handoff: AI may help with uncertain editorial work, but its
output must be clearly marked as a suggestion and must never be passed off as
finished. So every drafted description is written into the sidecar file under an
explicit `UNREVIEWED` marker, and the file says at the top that nothing in it
should be published unread.

Three sources of text, in order of trust:

1. **Existing alt text** from the old `<img>`. A real person wrote it. Carried
   through unchanged and marked `KEPT`.
2. **A model's draft**, if an API key is present. Marked `UNREVIEWED`.
3. **Nothing**, when there is no key and no existing alt. Marked `TODO` — a
   blank is better than a fabrication.

The app never invents a description from a filename. "screenshot-3.png" tells
you nothing about what the screenshot shows, and a plausible-sounding guess is
worse than an obvious gap because it survives review.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.images import ImagePlan, ImageReport


MODEL = "claude-sonnet-4-6"
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
TIMEOUT = 60.0

MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

PROMPT = """You are writing accessibility alt text and a media-library title for an image from a Dyalog APL technical blog post.

Context from the post around this image:
<context>
{context}
</context>

Write:
1. ALT: one sentence describing what the image shows, for a screen-reader user who cannot see it. If it is a screenshot of an APL session, say what is being demonstrated and name the specific functions or results visible. Do not begin with "Image of" or "Screenshot of". Under 125 characters.
2. TITLE: a short human-readable title, under 60 characters, in sentence case.

If you cannot tell what the image shows, reply exactly:
UNCLEAR

Otherwise reply with exactly two lines:
ALT: ...
TITLE: ..."""


@dataclass
class Draft:
    alt: str = ""
    title: str = ""
    status: str = "TODO"  # KEPT | UNREVIEWED | TODO | FAILED
    detail: str = ""


def api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key or None


def _encode(path: Path) -> tuple[str, str] | None:
    media_type = MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        return None
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return media_type, data


def _parse(text: str) -> Draft:
    if "UNCLEAR" in text.upper() and "ALT:" not in text.upper():
        return Draft(status="TODO", detail="The model could not tell what the image shows.")
    alt = title = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("ALT:"):
            alt = stripped[4:].strip()
        elif stripped.upper().startswith("TITLE:"):
            title = stripped[6:].strip()
    if not alt:
        return Draft(status="FAILED", detail="No usable description in the reply.")
    return Draft(alt=alt, title=title, status="UNREVIEWED")


def draft_one(plan: ImagePlan, context: str, key: str, client: httpx.Client) -> Draft:
    """Ask the model to describe one image. Never raises."""
    if plan.source is None:
        return Draft(status="TODO", detail="No source file.")
    encoded = _encode(plan.source)
    if encoded is None:
        return Draft(status="TODO", detail=f"Cannot send {plan.source.suffix} to the model.")
    media_type, data = encoded

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
                "max_tokens": 300,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": data,
                                },
                            },
                            {"type": "text", "text": PROMPT.format(context=context or "(none)")},
                        ],
                    }
                ],
            },
        )
    except httpx.HTTPError as exc:
        return Draft(status="FAILED", detail=f"Request failed: {type(exc).__name__}.")

    if response.status_code != 200:
        return Draft(
            status="FAILED",
            detail=f"The API answered {response.status_code}.",
        )

    try:
        blocks = response.json().get("content", [])
        text = "\n".join(block.get("text", "") for block in blocks if block.get("type") == "text")
    except ValueError:
        return Draft(status="FAILED", detail="Could not read the API reply.")

    return _parse(text)


def draft_all(
    report: ImageReport,
    contexts: dict[int, str] | None = None,
    client: httpx.Client | None = None,
) -> dict[int, Draft]:
    """Draft text for every matched image.

    Existing alt text wins: a description written by a person is better evidence
    than anything a model produces, and section 2 says not to replace supplied
    content.
    """
    contexts = contexts or {}
    drafts: dict[int, Draft] = {}
    key = api_key()

    owns_client = client is None
    if key and owns_client:
        client = httpx.Client(timeout=TIMEOUT)

    try:
        for plan in report.matched:
            if plan.existing_alt:
                drafts[plan.index] = Draft(
                    alt=plan.existing_alt,
                    title=plan.existing_alt[:60],
                    status="KEPT",
                    detail="Alt text from the original page, unchanged.",
                )
                continue
            if not key or client is None:
                drafts[plan.index] = Draft(
                    status="TODO",
                    detail=(
                        "No ANTHROPIC_API_KEY is set, so no draft was generated. "
                        "Write a description here."
                    ),
                )
                continue
            drafts[plan.index] = draft_one(plan, contexts.get(plan.index, ""), key, client)
    finally:
        if owns_client and client is not None:
            client.close()

    return drafts


def sidecar_text(report: ImageReport, drafts: dict[int, Draft], slug: str) -> str:
    """The text file written next to the processed images."""
    lines = [
        f"Images for: {slug}",
        "",
        "NOTHING IN THIS FILE HAS BEEN PUBLISHED OR CHECKED.",
        "",
        "  KEPT       alt text from the original page, written by a person.",
        "  UNREVIEWED drafted by a model. Read it against the image before using it.",
        "  TODO       no description. Write one.",
        "  FAILED     drafting was attempted and did not work. Write one.",
        "",
        "-" * 70,
        "",
    ]

    for plan in report.plans:
        draft = drafts.get(plan.index, Draft())
        lines.append(f"{plan.output_name}")
        if not plan.matched:
            lines.append(f"  STATUS   NOT PROCESSED - {plan.note}")
            lines.append(f"  SRC      {plan.src_attribute}")
            lines.append("")
            continue
        lines.append(f"  STATUS   {draft.status}")
        lines.append(f"  ALT      {draft.alt}")
        lines.append(f"  TITLE    {draft.title}")
        lines.append(f"  SIZE     {plan.width}x{plan.height}px, {plan.kind}, {plan.encoding}")
        if plan.undersize:
            lines.append(f"  WARNING  {plan.note}")
        lines.append(f"  FROM     {plan.source.name if plan.source else '?'}")
        if draft.detail:
            lines.append(f"  NOTE     {draft.detail}")
        lines.append("")

    if report.unreferenced:
        lines.append("-" * 70)
        lines.append("")
        lines.append("Files in the folder that no <img> in the post refers to:")
        for name in report.unreferenced:
            lines.append(f"  {name}")
        lines.append("")

    if report.errors:
        lines.append("-" * 70)
        lines.append("")
        lines.append("Problems:")
        for error in report.errors:
            lines.append(f"  {error}")
        lines.append("")

    return "\n".join(lines)
