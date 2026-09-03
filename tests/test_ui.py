from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_results_page_has_working_finding_filter_controls():
    response = client.post(
        "/analyse",
        data={
            "source_type": "html",
            "content": '<p class="fclear">Use <span class="APLFont">⎕JSON</span>.</p>',
            "selector": "",
        },
    )

    assert response.status_code == 200
    html = response.text
    assert 'data-finding-filter="all"' in html
    assert 'data-finding-filter="safe"' in html
    assert 'data-finding-filter="suggested"' in html
    assert 'data-finding-filter="warning"' in html
    assert 'data-finding-filter="error"' in html
    assert 'data-finding-severity="safe"' in html
    assert 'id="finding-count"' in html
    assert 'id="empty-filter-message"' in html


def test_results_page_uses_compact_functional_heading_not_hero_copy():
    response = client.post(
        "/analyse",
        data={
            "source_type": "html",
            "content": "<p>Hello.</p>",
            "selector": "",
        },
    )

    assert response.status_code == 200
    html = response.text
    assert '<h1>Results</h1>' in html
    assert "Your Blogsterized HTML" not in html
    assert "Analysis complete" not in html
    assert "summary-grid" not in html


def test_home_page_is_compact_and_has_profile_details_collapsed():
    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert '<h1>Analyse content</h1>' in html
    assert "Give it a page" not in html
    assert 'class="profile-details"' in html
    assert '>Blogsterize<' in html


def test_health_reports_current_app_name():
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json()['app'] == 'The Blogsterizer'


def test_version_is_consistent_everywhere():
    """One source of truth.

    This used to assert a literal, which is how the app went thirteen packaged
    builds still calling itself 0.5.0: bumping the version broke the test, so
    only the zip filename ever changed.
    """
    import re

    from app.main import app
    from app.version import __version__

    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__
    assert app.version == __version__

    pyproject = (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert 'attr = "app.version.__version__"' in pyproject, "pyproject must read the version"
    assert f'version = "{__version__}"' not in pyproject, "version must not be duplicated"


def test_version_is_visible_in_the_interface():
    from app.version import __version__

    client = TestClient(app)
    assert f"v{__version__}" in client.get("/").text
    assert client.get("/health").json()["version"] == __version__


def test_api_report_includes_export_safe():
    response = client.post('/api/analyse', json={
        'source_type': 'html',
        'content': '<p>Use <code>words</code>.</p>',
    })
    assert response.status_code == 200
    assert response.json()['export_safe'] is True
