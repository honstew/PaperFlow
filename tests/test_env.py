from __future__ import annotations

import shutil

import pytest

from paperflow.core.env import (
    EnvDetector,
    EnvItem,
    EnvReport,
    EnvStatus,
    _error_tail,
)


def test_env_report_can_compile_and_summary() -> None:
    items = [
        EnvItem("xelatex", "XeLaTeX", EnvStatus.OK, "ok"),
        EnvItem("packages", "packages", EnvStatus.OK, "ok"),
        EnvItem("fonts", "fonts", EnvStatus.OK, "ok"),
        EnvItem("compile", "compile", EnvStatus.OK, "ok"),
        EnvItem("biber", "biber", EnvStatus.WARN, "missing"),
    ]
    report = EnvReport(items=items)
    assert report.can_compile is True
    assert report.references_ready is False
    assert "4 项通过" in report.summary
    assert "1 项警告" in report.summary


def test_env_report_requires_compile_probe() -> None:
    report = EnvReport(items=[EnvItem("xelatex", "XeLaTeX", EnvStatus.OK, "ok")])
    assert report.can_compile is False
    assert report.missing == []


def test_error_tail_prefers_actionable_lines() -> None:
    text = (
        "This is XeTeX\n"
        "! Font \\TU/SimSun(0)/m/n/10.5 not found.\n"
        "l.12 ...\n"
        "Output written on probe.pdf (0 pages).\n"
    )
    tail = _error_tail(text, "")
    assert "Font" in tail or "not found" in tail


@pytest.mark.skipif(shutil.which("xelatex") is None, reason="XeLaTeX not installed")
def test_real_environment_detects_xelatex() -> None:
    report = EnvDetector().detect()
    item = report.get("xelatex")
    assert item is not None
    assert item.status is EnvStatus.OK
    assert report.can_compile is True