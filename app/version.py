"""The one place the version number lives.

Everything else imports it: the FastAPI app, the page footer, the packaged
artefact. Up to 0.10.x the version was only ever changed in the name of the zip
file, so pyproject.toml and the running app both still claimed 0.5.0 and there
was no way to tell from the interface which build was in front of you.

Versioning, while below 1.0:

* patch (0.11.x) — a bug fix or a change with no new capability
* minor (0.x.0)  — a new capability, or a change to how something behaves
* 1.0.0          — when the deterministic cleaner is trusted against real
                   content and the WordPress round trip is verified end to end
"""

__version__ = "0.19.4"
