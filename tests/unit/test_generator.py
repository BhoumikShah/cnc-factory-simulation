from vmc_twin.data.generator import SyntheticDataGenerator


def test_generator_deterministic_reproducibility() -> None:
    gen1 = SyntheticDataGenerator(random_seed=123)
    jobs1 = gen1.generate_jobs(count=20, horizon_minutes=1000.0)

    gen2 = SyntheticDataGenerator(random_seed=123)
    jobs2 = gen2.generate_jobs(count=20, horizon_minutes=1000.0)

    assert len(jobs1) == 20
    assert len(jobs2) == 20

    for j1, j2 in zip(jobs1, jobs2):
        assert j1.job_id == j2.job_id
        assert j1.release_time == j2.release_time
        assert j1.due_date == j2.due_date
        assert len(j1.operations) == len(j2.operations)
        for op1, op2 in zip(j1.operations, j2.operations):
            assert op1.op_id == op2.op_id
            assert op1.nominal_cycle_minutes == op2.nominal_cycle_minutes
