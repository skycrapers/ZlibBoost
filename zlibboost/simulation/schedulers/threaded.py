"""Threaded simulation scheduler implementation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from dataclasses import dataclass
from typing import Iterable, List, Dict, Callable, Sequence

from zlibboost.core.logger import get_logger
from zlibboost.simulation.jobs.job import SimulationJob, SimulationResult

logger = get_logger(__name__)


@dataclass
class SchedulerStats:
    """Lightweight statistics emitted by the scheduler after execution."""

    submitted: int
    completed: int
    failed: int


class SimulationScheduler:
    """Threaded scheduler that orders and executes simulation jobs."""

    def __init__(self, max_workers: int | None = None) -> None:
        self.max_workers = max_workers or 1

    # ------------------------------------------------------------------
    # Weighting helpers used for ordering jobs (legacy parity)
    # ------------------------------------------------------------------
    def weight_for_arc(self, arc: object) -> int:
        """Return the scheduling weight for a TimingArc-like object."""

        timing_type = getattr(arc, "timing_type", "") or ""
        table_type = getattr(arc, "table_type", "") or ""
        timing_type_lower = timing_type.lower()
        table_type_lower = table_type.lower()

        if any(key in timing_type_lower for key in (
            "setup", "hold", "recovery", "removal", "non_seq_setup", "non_seq_hold"
        )):
            return 4

        if timing_type_lower == "min_pulse_width" or table_type_lower == "min_pulse_width":
            return 3

        if table_type_lower in {"rise_transition", "fall_transition", "input_capacitance"}:
            return 2

        if table_type_lower == "leakage_power":
            return 1

        return 1

    def weight_for_job(self, job: SimulationJob) -> int:
        """Return the scheduling weight for the provided job."""

        if job.arc is not None:
            return self.weight_for_arc(job.arc)
        if "weight" in job.metadata:
            return int(job.metadata["weight"])
        return 1

    def order_tasks(self, arcs: Sequence[object]) -> List[object]:
        """Sort arcs by weight in descending order, keeping stability."""

        return sorted(arcs, key=self.weight_for_arc, reverse=True)

    # ------------------------------------------------------------------
    # Execution interface
    # ------------------------------------------------------------------
    def run(self, jobs: Iterable[SimulationJob], worker: Callable[[SimulationJob], SimulationResult]) -> Dict[str, SimulationResult]:
        """Execute the provided jobs using a thread pool.

        Args:
            jobs: Iterable of :class:`SimulationJob`.
            worker: Callable that receives a job and returns a :class:`SimulationResult`.

        Returns:
            Mapping of job_id to :class:`SimulationResult`.
        """

        serial_results: Dict[str, SimulationResult] = {}
        parallel_jobs: List[SimulationJob] = []
        serial_count = 0

        for job in jobs:
            if job.requires_serial:
                serial_count += 1
                result = self._run_serial(job, worker)
                serial_results[job.job_id] = result
            else:
                parallel_jobs.append(job)

        parallel_count = len(parallel_jobs)
        total_jobs = serial_count + parallel_count
        logger.info(
            "Scheduler dispatching %d jobs (parallel=%d, serial=%d) with max_workers=%d",
            total_jobs,
            parallel_count,
            serial_count,
            self.max_workers,
        )

        parallel_results = self._run_parallel(parallel_jobs, worker) if parallel_jobs else {}

        return {**serial_results, **parallel_results}

    def _run_serial(self, job: SimulationJob, worker: Callable[[SimulationJob], SimulationResult]) -> SimulationResult:
        """Run a job without using the thread pool."""

        try:
            return worker(job)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Simulation job %s failed in serial path: %s", job.job_id, exc)
            return SimulationResult(job=job, status="failed", engine="unknown", data={}, error=str(exc))

    def _run_parallel(self, jobs: List[SimulationJob], worker: Callable[[SimulationJob], SimulationResult]) -> Dict[str, SimulationResult]:
        """Run jobs within a thread pool respecting job weights."""

        if not jobs:
            return {}

        # Sort jobs by weight to prioritise heavier workloads first
        ordered_jobs = sorted(jobs, key=self.weight_for_job, reverse=True)

        results: Dict[str, SimulationResult] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_job: Dict[Future[SimulationResult], SimulationJob] = {}
            for job in ordered_jobs:
                future = pool.submit(self._safe_worker, worker, job)
                future_to_job[future] = job

            for future in as_completed(future_to_job):
                job = future_to_job[future]
                try:
                    result = future.result()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.error("Simulation job %s failed: %s", job.job_id, exc)
                    result = SimulationResult(job=job, status="failed", engine="unknown", data={}, error=str(exc))
                results[job.job_id] = result

        return results

    @staticmethod
    def _safe_worker(worker: Callable[[SimulationJob], SimulationResult], job: SimulationJob) -> SimulationResult:
        """Wrapper used to isolate worker exceptions."""

        return worker(job)
