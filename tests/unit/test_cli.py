from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from vmc_twin.cli import app

runner = CliRunner()


def test_cli_info() -> None:
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    assert "CNC VMC Shop Floor Digital Twin" in result.stdout


def test_cli_simulate_and_diagnose(tmp_path: Path) -> None:
    db_out = str(tmp_path / "sim.db")
    html_out = str(tmp_path / "gantt.html")
    res_sim = runner.invoke(
        app,
        [
            "run",
            "configs/scenarios/baseline.yaml",
            "--db",
            db_out,
            "--html",
            html_out,
        ],
    )
    assert res_sim.exit_code == 0
    assert "Fleet KPIs" in res_sim.stdout
    assert Path(db_out).exists()

    # Test Diagnose
    md_out = str(tmp_path / "diag.md")
    json_out = str(tmp_path / "diag.json")
    res_diag = runner.invoke(
        app,
        [
            "diagnose",
            "configs/scenarios/baseline.yaml",
            "--md",
            md_out,
            "--json",
            json_out,
        ],
    )
    assert res_diag.exit_code == 0
    assert Path(md_out).exists()
    assert Path(json_out).exists()


def test_cli_predict_wear() -> None:
    res_wear = runner.invoke(app, ["predict-wear", "configs/scenarios/baseline.yaml"])
    assert res_wear.exit_code == 0
    assert "Cutting Tool Degradation" in res_wear.stdout


def test_cli_report(tmp_path: Path) -> None:
    rep_out = str(tmp_path / "full_report.html")
    res_rep = runner.invoke(
        app,
        [
            "report",
            "configs/scenarios/baseline.yaml",
            "--output",
            rep_out,
        ],
    )
    assert res_rep.exit_code == 0
    assert Path(rep_out).exists()
