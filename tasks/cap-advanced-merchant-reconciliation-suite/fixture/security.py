"""Admin auth, safe export paths, HTML escaping (stub).

Admin token comes from RECON_ADMIN_TOKEN, defaulting to recon-admin.
"""
import os

DEFAULT_ADMIN_TOKEN = "recon-admin"


def admin_token() -> str:
    """Return the configured admin token."""
    return os.environ.get("RECON_ADMIN_TOKEN", DEFAULT_ADMIN_TOKEN)


def verify_admin_token(provided: str | None) -> bool:
    """TODO: compare provided token against admin_token() (constant-time);
    routes return 401 when this is false.
    """
    raise NotImplementedError("TODO: implement X-Admin-Token check")


def safe_export_path(requested: str) -> str:
    """TODO: resolve the requested export destination inside the export
    directory; reject path traversal.
    """
    raise NotImplementedError("TODO: implement safe export path resolution")


def escape_html(text: str) -> str:
    """TODO: escape &, <, >, double-quote, single-quote for HTML views."""
    raise NotImplementedError("TODO: implement HTML escaping")
