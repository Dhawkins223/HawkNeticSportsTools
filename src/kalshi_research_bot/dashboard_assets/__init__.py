"""Static assets for the research dashboard.

The stylesheet and script live as real files rather than Python string
constants so they can be linted, formatted, and diffed like the code they are.
They are read once at import time and served from hashed URLs, which lets the
browser cache them hard while the HTML itself stays `no-store`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ASSET_ROOT = Path(__file__).resolve().parent

# Media types for everything this package serves.
ASSET_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".woff2": "font/woff2",
}


def _read(name: str) -> bytes:
    return (ASSET_ROOT / name).read_bytes()


def _fingerprint(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:12]


class Asset:
    """One served file, addressed by a URL that changes when its bytes do."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.body = _read(name)
        self.fingerprint = _fingerprint(self.body)
        self.content_type = ASSET_CONTENT_TYPES[Path(name).suffix]

    @property
    def url(self) -> str:
        stem = Path(self.name).stem
        suffix = Path(self.name).suffix
        return f"/assets/{stem}.{self.fingerprint}{suffix}"


STYLESHEET = Asset("app.css")
SCRIPT = Asset("app.js")
LOGIN_SCRIPT = Asset("login.js")
OPS_SCRIPT = Asset("ops.js")
FONT_LATIN = Asset("inter-latin.woff2")
FONT_LATIN_EXT = Asset("inter-latin-ext.woff2")

_ALL = (STYLESHEET, SCRIPT, LOGIN_SCRIPT, OPS_SCRIPT, FONT_LATIN, FONT_LATIN_EXT)
ASSETS = {asset.url: asset for asset in _ALL}


def stylesheet_css() -> str:
    """The stylesheet with font URLs resolved to their hashed paths."""
    css = STYLESHEET.body.decode("utf-8")
    return css.replace("__INTER_LATIN__", FONT_LATIN.url).replace(
        "__INTER_LATIN_EXT__", FONT_LATIN_EXT.url
    )


# The font URLs are substituted into the CSS, so the stylesheet a browser
# receives differs from the file on disk; fingerprint what is actually sent.
_RESOLVED_CSS = stylesheet_css().encode("utf-8")
STYLESHEET.body = _RESOLVED_CSS
STYLESHEET.fingerprint = _fingerprint(_RESOLVED_CSS)
ASSETS = {asset.url: asset for asset in _ALL}


def lookup(path: str) -> Asset | None:
    return ASSETS.get(path)
