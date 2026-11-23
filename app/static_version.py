"""
Version stamp on our own scripts and stylesheets ("/static/js/app.js" -> "/static/js/app.js?v=1730790000"),
so browsers fetch the new file after an update instead of running a cached old one against a new page.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIRS = (("/pos/static/", ROOT / "pos" / "static" / "pos"), ("/static/", ROOT / "app" / "static"))


def versioned(url: str) -> str:
    for prefix, directory in STATIC_DIRS:
        if url.startswith(prefix):
            try:
                return f"{url}?v={int((directory / url[len(prefix):]).stat().st_mtime)}"
            except OSError:
                return url
    return url


def add_version_filter(templates) -> None:
    templates.env.filters["v"] = versioned
