"""
FiBand - Flask front controller / entry point.

Every request lands here:
  1. dispatches the AJAX actions (sync / save_note / ai_prompt) via the
     `actions` blueprint,
  2. otherwise resolves the dashboard data and renders ONE page
     (?page=overview|charts|sleep|diary|log|actions, default overview).

Run directly with `python app.py` (dev server on 127.0.0.1:8080), or via
`bash start.command`.
"""
from __future__ import annotations

from datetime import datetime

from flask import Flask, render_template, request

from fiband.actions import bp as actions_bp
from fiband.config import OPENROUTER_MODEL
from fiband.dashboard import dashboard_data
from fiband.helpers import (
    card_val, delta_badge, hhmm, recent_value, row_value,
    sleep_panel_body, sleep_totals, tipo_label, tlabel, tlocal,
)
from fiband.webdb import close_db, get_db

PAGES = ("overview", "charts", "sleep", "diary", "log", "actions")
TEMPLATE_FOR_PAGE = {
    "charts": "charts.html", "sleep": "sleep.html", "log": "log.html",
    "diary": "diary.html", "actions": "actions.html", "overview": "overview.html",
}


def daylabel(d: str) -> str:
    """'YYYY-MM-DD' -> 'DD/MM'."""
    return datetime.strptime(d, "%Y-%m-%d").strftime("%d/%m")


def daylabel_full(d: str) -> str:
    """'YYYY-MM-DD' -> 'DD/MM/YYYY'."""
    return datetime.strptime(d, "%Y-%m-%d").strftime("%d/%m/%Y")


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.teardown_appcontext(close_db)
    app.register_blueprint(actions_bp)

    app.jinja_env.globals.update(
        card_val=card_val, delta_badge=delta_badge, hhmm=hhmm, row_value=row_value,
        recent_value=recent_value, sleep_panel_body=sleep_panel_body, sleep_totals=sleep_totals,
        tipo_label=tipo_label, tlabel=tlabel, tlocal=tlocal, daylabel=daylabel, daylabel_full=daylabel_full,
    )
    app.jinja_env.filters.update(tlabel=tlabel, tlocal=tlocal, daylabel=daylabel, daylabel_full=daylabel_full)

    @app.route("/")
    def index():
        page = request.args.get("page", "")
        if page not in PAGES:
            page = "overview"
        ctx = dashboard_data(get_db(), request.args)
        ctx["page"] = page
        ctx["OPENROUTER_MODEL"] = OPENROUTER_MODEL
        return render_template(TEMPLATE_FOR_PAGE[page], **ctx)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=False)
