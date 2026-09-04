"""Submit the forms the page actually renders.

The suite previously hand-built every POST to /apply, which meant it never
exercised the rendered HTML. A JSON attribute was being written unescaped —
`value="{"index": 0}"` terminates at the first inner quote — so every real
click produced a 500 while the tests stayed green. These tests parse the page
and submit what a browser would submit.
"""
from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app.main import app

FIXTURE = Path(__file__).parent / "fixtures" / "hashing-it-out.html"
LONG_PARAGRAPH = "<p>" + ("One sentence here. " * 40) + "Final sentence here.</p>"


def submit(client: TestClient, form) -> "object":
    """Post a rendered form exactly as a browser would."""
    data = {}
    for field in form.find_all("input"):
        if field.get("name"):
            data[field["name"]] = field.get("value", "")
    return client.post(form["action"], data=data)


def analyse(client: TestClient, content: str):
    return client.post(
        "/analyse", data={"source_type": "html", "content": content, "selector": ""}
    )


def test_json_attributes_are_escaped_so_the_form_survives_the_browser():
    client = TestClient(app)
    page = analyse(client, LONG_PARAGRAPH).text
    # An unescaped attribute would read: value="{"index": 0, ...}"
    assert 'value="{"' not in page
    assert "&#34;index&#34;" in page


def test_clicking_split_here_works():
    client = TestClient(app)
    page = analyse(client, LONG_PARAGRAPH)
    form = BeautifulSoup(page.text, "html.parser").find("form", class_="finding-action")
    assert form is not None

    response = submit(client, form)
    assert response.status_code == 200
    assert "Applied:" in response.text
    assert "Fixed <strong>1</strong>" in response.text


def test_clicking_every_offered_action_on_the_real_post_succeeds():
    """One click at a time, from a fresh analysis, for each action the page offers."""
    client = TestClient(app)
    source = FIXTURE.read_text(encoding="utf-8")
    page = analyse(client, source)
    forms = BeautifulSoup(page.text, "html.parser").find_all("form", class_="finding-action")
    assert len(forms) >= 13

    for form in forms:
        response = submit(client, form)
        action = form.find("input", {"name": "action"})["value"]
        assert response.status_code == 200, action
        assert "Applied:" in response.text, action


def test_clicks_can_be_chained_through_the_rendered_pages():
    """Apply, then apply again from the page that came back, then undo."""
    client = TestClient(app)
    page = analyse(client, FIXTURE.read_text(encoding="utf-8"))

    for expected in (1, 2, 3):
        form = BeautifulSoup(page.text, "html.parser").find("form", class_="finding-action")
        page = submit(client, form)
        assert page.status_code == 200
        assert f"Fixed <strong>{expected}</strong>" in page.text

    undo = BeautifulSoup(page.text, "html.parser").find("form", action="/undo")
    assert undo is not None
    page = submit(client, undo)
    assert page.status_code == 200
    assert "Fixed <strong>2</strong>" in page.text


def test_duplicate_id_form_submits_its_suggested_value():
    client = TestClient(app)
    page = analyse(
        client,
        '<h2 id="distraction-1">Tangent #1</h2><p id="distraction-1"><strong>Distraction #1</strong></p>',
    )
    soup = BeautifulSoup(page.text, "html.parser")
    form = next(
        f for f in soup.find_all("form", class_="finding-action")
        if f.find("input", {"name": "action"})["value"] == "set_id"
    )
    # The first form offered is the first occurrence, suggesting a slug of its
    # own text. Renaming either side resolves the collision.
    assert form.find("input", {"name": "value"})["value"] == "tangent-1"

    response = submit(client, form)
    assert response.status_code == 200
    assert "Applied:" in response.text
    assert "SEO-DUPLICATE-ID-001" not in response.text


def test_malformed_form_state_does_not_produce_a_server_error():
    client = TestClient(app)
    response = client.post(
        "/apply",
        data={
            "source": "<p>Text.</p>",
            "history": "{not json",
            "action": "split_paragraph",
            "params": "{also not json",
        },
    )
    assert response.status_code == 200
    assert "could not be read" in response.text
    assert "Text." in response.text


def test_no_endpoint_returns_a_server_error_for_the_real_post():
    client = TestClient(app)
    source = FIXTURE.read_text(encoding="utf-8")
    assert analyse(client, source).status_code == 200
    assert client.post("/undo", data={"source": source, "history": "[]"}).status_code == 200


# --------------------------------------------------------------------------
# Taking the output away with warnings still open
# --------------------------------------------------------------------------

JS = (Path(__file__).parent.parent / "app" / "static" / "app.js").read_text(encoding="utf-8")


def test_open_warning_count_is_published_to_the_page():
    client = TestClient(app)
    page = analyse(client, FIXTURE.read_text(encoding="utf-8")).text
    assert 'data-open-warnings="3"' in page


def test_export_toolbars_show_the_unresolved_count():
    client = TestClient(app)
    page = analyse(client, FIXTURE.read_text(encoding="utf-8")).text
    # One note beside Clean HTML's buttons, one beside Block markup's.
    assert page.count("toolbar-note") == 2
    assert "3 unresolved warnings" in page


def test_no_warning_shown_when_nothing_is_open():
    client = TestClient(app)
    page = analyse(client, "<p>Ordinary copy with nothing wrong.</p>").text
    assert 'data-open-warnings="0"' in page
    assert "toolbar-note" not in page


def test_resolving_a_warning_reduces_the_export_count():
    client = TestClient(app)
    source = '<h1>Addendum</h1><p>Text.</p>'
    before = analyse(client, source).text
    assert 'data-open-warnings="1"' in before

    after = client.post(
        "/apply",
        data={
            "source": source,
            "history": "[]",
            "action": "demote_heading",
            "params": '{"tag": "h1", "index": 0}',
        },
    ).text
    assert 'data-open-warnings="0"' in after
    assert "toolbar-note" not in after


def test_copy_and_download_ask_before_exporting_with_open_warnings():
    """The dialog must be a question, not a block: the user can proceed."""
    assert "confirmDespiteWarnings" in JS
    assert "window.confirm" in JS
    # Both export paths are guarded.
    copy_body = JS[JS.index("async function copyText"):JS.index("function downloadText")]
    download_body = JS[JS.index("function downloadText"):JS.index("function activateTab")]
    assert "confirmDespiteWarnings()" in copy_body
    assert "confirmDespiteWarnings()" in download_body
    # No warnings means no dialog at all.
    assert "if (!count) return null;" in JS


# --------------------------------------------------------------------------
# Grouping and per-fix undo
# --------------------------------------------------------------------------

def test_findings_are_grouped_by_rule():
    from app.profiles import DEFAULT_PROFILE_ID, load_profile
    from app.session import build_session

    session = build_session(FIXTURE.read_text(encoding="utf-8"), load_profile(DEFAULT_PROFILE_ID))
    groups = session.finding_groups
    # Hundreds of findings, a handful of rules.
    assert len(groups) < 12
    assert sum(g["count"] for g in groups) == len(session.findings)

    # Most urgent first, and the big repeats gathered.
    assert groups[0]["severity"] == "warning"
    long_paragraphs = next(g for g in groups if g["rule_id"] == "PARAGRAPH-REVIEW-001")
    assert long_paragraphs["count"] == 7
    assert long_paragraphs["actionable"] == 7


def test_open_groups_start_expanded_and_completed_work_starts_collapsed():
    from app.profiles import DEFAULT_PROFILE_ID, load_profile
    from app.session import build_session

    session = build_session(FIXTURE.read_text(encoding="utf-8"), load_profile(DEFAULT_PROFILE_ID))
    for group in session.finding_groups:
        if group["severity"] in {"error", "warning"}:
            assert group["open"], group["rule_id"]
        else:
            assert not group["open"], group["rule_id"]


def test_groups_render_with_a_count_badge():
    client = TestClient(app)
    page = analyse(client, FIXTURE.read_text(encoding="utf-8")).text
    groups = page.count('class="finding-group')
    # One accordion per rule that fired; the exact number moves as rules are
    # added, so what matters is that the badges match the groups.
    assert groups >= 10
    assert page.count("data-group-count") == groups


def test_filtering_hides_groups_with_nothing_left_to_show():
    js = (Path(__file__).parent.parent / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert "data-group-severity" in js
    assert "group.hidden = shown === 0" in js
    assert "badge.textContent = shown" in js


def test_every_fix_is_listed_with_its_own_undo():
    client = TestClient(app)
    source = FIXTURE.read_text(encoding="utf-8")
    page = analyse(client, source)

    for _ in range(3):
        form = BeautifulSoup(page.text, "html.parser").find("form", class_="finding-action")
        page = submit(client, form)

    soup = BeautifulSoup(page.text, "html.parser")
    items = soup.select(".fixed-list li")
    assert len(items) == 3
    for position, item in enumerate(items):
        # Each row says what it did and can be undone on its own.
        assert item.find("span").get_text(strip=True)
        assert item.find("input", {"name": "index"})["value"] == str(position)


def test_undoing_an_earlier_fix_keeps_the_later_ones():
    client = TestClient(app)
    source = "<h1>Addendum</h1><p class=\"code-active-line\">Text.</p>"
    history = [
        {"action": "demote_heading", "params": {"tag": "h1", "index": 0}},
        {"action": "remove_class", "params": {"class_name": "code-active-line"}},
    ]
    import json as _json

    response = client.post(
        "/undo",
        data={"source": source, "history": _json.dumps(history), "index": 0},
    )
    assert response.status_code == 200
    assert "Fixed <strong>1</strong>" in response.text
    # The heading fix is undone, so its warning is back.
    assert "SEO-H1-001" in response.text
    # The class fix survived.
    assert "UNKNOWN-CLASS-001" not in response.text


# --------------------------------------------------------------------------
# A form submission must not throw you onto a different tab.
# --------------------------------------------------------------------------

import re as _re


def active_tab(page: str) -> str:
    match = _re.search(r'class="tab active" type="button" data-tab="(\w+)"', page)
    return match.group(1) if match else "?"


def test_analysing_starts_on_clean_html():
    client = TestClient(app)
    assert active_tab(analyse(client, LONG_PARAGRAPH).text) == "clean"


def test_checking_links_stays_on_the_links_tab():
    """Reported: pressing Check links dumped you back on Clean HTML."""
    client = TestClient(app)
    page = client.post(
        "/check-links",
        data={
            "source": '<p><a href="https://www.dyalog.com/a/">a</a></p>',
            "history": "[]",
            "mode": "current",
            "tab": "links",
        },
    ).text
    assert active_tab(page) == "links"
    assert 'data-panel="links" role="tabpanel" >' in page or 'data-panel="links"' in page


def test_drafting_yoast_fields_stays_on_the_yoast_tab():
    client = TestClient(app)
    page = client.post(
        "/seo-draft",
        data={"source": "<p>" + ("word " * 60) + "</p>", "history": "[]", "tab": "seo"},
    ).text
    assert active_tab(page) == "seo"


def test_applying_a_fix_stays_on_the_changes_tab():
    client = TestClient(app)
    page = client.post(
        "/apply",
        data={
            "source": "<h1>Addendum</h1><p>Text.</p>",
            "history": "[]",
            "action": "demote_heading",
            "params": '{"tag": "h1", "index": 0}',
            "tab": "changes",
        },
    ).text
    assert active_tab(page) == "changes"


def test_undoing_stays_on_the_changes_tab():
    client = TestClient(app)
    page = client.post(
        "/undo",
        data={"source": "<p>Text.</p>", "history": "[]", "tab": "changes"},
    ).text
    assert active_tab(page) == "changes"


def test_every_form_says_which_tab_it_came_from():
    """Otherwise the server cannot send the user back to it."""
    client = TestClient(app)
    page = analyse(client, FIXTURE.read_text(encoding="utf-8")).text
    soup = BeautifulSoup(page, "html.parser")
    forms = [f for f in soup.find_all("form") if f.get("action", "").startswith("/")]
    # /analyse is on the input page, not here; every form on the results page
    # posts back to it and so must carry the tab.
    assert forms
    for form in forms:
        assert form.find("input", {"name": "tab"}) is not None, form.get("action")


def test_submitting_a_rendered_form_returns_to_its_own_tab():
    """The whole point, exercised the way a browser does it."""
    client = TestClient(app)
    page = analyse(client, FIXTURE.read_text(encoding="utf-8"))
    form = BeautifulSoup(page.text, "html.parser").find("form", class_="finding-action")
    response = submit(client, form)
    assert active_tab(response.text) == "changes"
