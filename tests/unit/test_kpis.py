from pathlib import Path

from vmc_twin.domain.events import Event
from vmc_twin.domain.job import Job
from vmc_twin.domain.states import CauseCode, SpindleState
from vmc_twin.report.kpis import KPICalculator
from vmc_twin.report.plots import PlotlyVisualizer


def test_kpi_calculator_metrics() -> None:
    events = [
        Event(
            t_start=0.0,
            t_end=60.0,
            machine_id="VMC-01",
            job_id="JOB-01",
            op_id="OP1",
            state=SpindleState.CUTTING,
        ),
        Event(
            t_start=60.0,
            t_end=80.0,
            machine_id="VMC-01",
            job_id="JOB-02",
            op_id="OP1",
            state=SpindleState.SETUP,
        ),
        Event(
            t_start=80.0,
            t_end=100.0,
            machine_id="VMC-01",
            job_id=None,
            op_id=None,
            state=SpindleState.IDLE_STARVED,
            cause_code=CauseCode.NO_QUEUE_JOB,
        ),
    ]

    job1 = Job(
        job_id="JOB-01",
        part_name="P1",
        material="Al",
        priority=3,
        release_time=0.0,
        due_date=70.0,  # completed at t=60 -> On-time!
        operations=[],
    )

    kpis = KPICalculator.calculate(
        scenario_name="unit_test",
        horizon_minutes=100.0,
        events=events,
        jobs=[job1],
    )

    assert kpis.fleet_size == 1
    m_kpi = kpis.machine_kpis["VMC-01"]
    assert m_kpi.cutting_minutes == 60.0
    assert m_kpi.setup_minutes == 20.0
    assert m_kpi.idle_starved_minutes == 20.0
    assert m_kpi.utilization_pct == 60.0
    assert m_kpi.setup_pct == 20.0
    assert m_kpi.idle_pct == 20.0
    assert kpis.on_time_delivery_pct == 100.0
    assert kpis.makespan_minutes == 80.0


def test_plotly_visualizer_html_export(tmp_path: Path) -> None:
    events = [
        Event(
            t_start=0.0,
            t_end=30.0,
            machine_id="VMC-01",
            job_id="JOB-01",
            op_id="OP1",
            state=SpindleState.CUTTING,
        ),
        Event(
            t_start=30.0,
            t_end=45.0,
            machine_id="VMC-01",
            job_id="JOB-02",
            op_id="OP1",
            state=SpindleState.SETUP,
        ),
    ]

    job1 = Job(
        job_id="JOB-01",
        part_name="P1",
        material="Al",
        priority=3,
        release_time=0.0,
        due_date=50.0,
        operations=[],
    )

    kpis = KPICalculator.calculate(
        scenario_name="html_test",
        horizon_minutes=60.0,
        events=events,
        jobs=[job1],
    )

    out_file = tmp_path / "test_gantt.html"
    exported_path = PlotlyVisualizer.export_dashboard_html(kpis, events, output_path=out_file)

    assert exported_path.exists()
    content = exported_path.read_text(encoding="utf-8")
    assert "CNC VMC Digital Twin" in content
    assert "html_test" in content
