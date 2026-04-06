"""Shared Jinja2 environment for server-side rendering."""

from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

_env = Environment(loader=FileSystemLoader("templates"), autoescape=True, cache_size=0)


def render(template_name: str, **context) -> HTMLResponse:
    """Render a Jinja2 template and return an HTMLResponse."""
    return HTMLResponse(_env.get_template(template_name).render(**context))
