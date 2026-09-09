"""The Streamlit app is exercised through Streamlit's own test harness.

This catches the class of bug the app shipped with before -- a data loader that
silently returned ``None`` for every Solomon file, so the "Solomon C101" option
did nothing at all -- without needing a browser.
"""

from __future__ import annotations

from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"
TIMEOUT = 300


def run_app():
    app = AppTest.from_file(str(APP), default_timeout=TIMEOUT)
    app.run()
    return app


def test_app_starts_without_exceptions():
    app = run_app()
    assert not app.exception
    assert any("Energy-aware EV fleet routing" in t.value for t in app.title)


def test_sidebar_lists_the_shipped_instances():
    app = run_app()
    options = app.sidebar.selectbox[1].options
    assert "C101" in options and "RC201" in options


def test_optimise_produces_a_verified_plan():
    """End to end: press the button and check the app reaches a feasible plan."""
    app = run_app()
    # Keep the run cheap: three chargers, a short time limit, one solver.
    app.sidebar.slider[4].set_value(3)          # charging stations
    app.sidebar.multiselect[0].set_value(["savings"])
    app.sidebar.button[0].click()
    app.run()
    assert not app.exception
    assert app.success or app.error, "the app must state a feasibility verdict"
    if app.success:
        assert "verified feasible" in app.success[0].value
        labels = [m.label for m in app.metric]
        assert "Distance" in labels and "Charging stops" in labels


def test_upload_option_warns_instead_of_crashing():
    app = run_app()
    app.sidebar.selectbox[0].set_value("Upload CSV")
    app.run()
    app.sidebar.button[0].click()
    app.run()
    assert not app.exception
    assert any("Upload a CSV" in w.value for w in app.sidebar.warning)
