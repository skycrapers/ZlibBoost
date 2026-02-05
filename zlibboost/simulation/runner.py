"""High-level simulation runner that orchestrates deck execution."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

from zlibboost.core.exceptions import ConfigurationError
from zlibboost.core.logger import get_logger
from zlibboost.database.library_db import CellLibraryDB
from zlibboost.database.models.timing_arc import TimingArc
from zlibboost.simulation.executors import (
    BaseSimulationExecutor,
    DelaySimulationExecutor,
    ConstraintSimulationExecutor,
    HiddenSimulationExecutor,
    LeakageSimulationExecutor,
    MockSimulationExecutor,
    MpwSimulationExecutor,
)
from zlibboost.simulation.writers import (
    DelayResultWriter,
    ConstraintResultWriter,
    HiddenResultWriter,
    LeakageResultWriter,
    MpwResultWriter,
    ResultWriterRegistry,
)
from zlibboost.simulation.generators.factory import SpiceGeneratorFactory
from zlibboost.simulation.jobs.job import SimulationJob, SimulationResult
from zlibboost.simulation.schedulers import SimulationScheduler

logger = get_logger(__name__)


class SimulationOrchestrator:
    """Coordinate simulation jobs using a scheduler and executor registry."""

    def __init__(
        self,
        library_db: CellLibraryDB,
        engine: str,
        scheduler: SimulationScheduler,
        writers: ResultWriterRegistry | None = None,
    ) -> None:
        self.library_db = library_db
        self.engine = engine.lower()
        self.scheduler = scheduler
        self._executor_cache: Dict[tuple[str, str], BaseSimulationExecutor] = {}
        self._writers = writers or ResultWriterRegistry(
            [
                DelayResultWriter(library_db),
                ConstraintResultWriter(library_db),
                HiddenResultWriter(library_db),
                LeakageResultWriter(library_db),
                MpwResultWriter(library_db),
            ]
        )
        self._attach_writers()

    def run(self, jobs: Iterable[SimulationJob]) -> Dict[str, SimulationResult]:
        """Execute jobs and write per-cell summaries."""

        results = self.scheduler.run(jobs, self._execute_job)
        self._write_cell_summaries(results)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _execute_job(self, job: SimulationJob) -> SimulationResult:
        executor = self._resolve_executor(job)
        payload = executor.simulate(job.deck_path, job.metadata, job.output_dir)
        result = SimulationResult(
            job=job,
            status=payload.get("status", "completed"),
            engine=payload.get("engine", self.engine),
            data=payload,
            error=payload.get("error"),
            elapsed=payload.get("elapsed"),
        )
        self._dispatch_write(result)
        return result

    def _resolve_executor(self, job: SimulationJob) -> BaseSimulationExecutor:
        key = (self.engine, job.sim_type)
        if key in self._executor_cache:
            return self._executor_cache[key]

        executor = self._create_executor(job)
        self._executor_cache[key] = executor
        return executor

    def _create_executor(self, job: SimulationJob) -> BaseSimulationExecutor:
        if self.engine == "mock":
            return MockSimulationExecutor()
        normalized_type = (job.sim_type or "").lower()
        if normalized_type == "delay":
            return DelaySimulationExecutor(engine=self.engine)
        if normalized_type in {"setup", "hold", "recovery", "removal"}:
            return ConstraintSimulationExecutor(engine=self.engine)
        if normalized_type == "hidden":
            return HiddenSimulationExecutor(engine=self.engine)
        if normalized_type == "leakage":
            return LeakageSimulationExecutor(engine=self.engine)
        if normalized_type == "mpw":
            return MpwSimulationExecutor(engine=self.engine)
        # Fallback to mock until dedicated executors are implemented.
        logger.warning(
            "No dedicated executor for sim_type=%s with engine=%s; using mock fallback",
            job.sim_type,
            self.engine,
        )
        return MockSimulationExecutor()

    def _dispatch_write(self, result: SimulationResult) -> None:
        writer = self._writers.get(result.job.sim_type)
        if writer is None:
            return
        writer.write(result)

    def _attach_writers(self) -> None:
        for writer in self._writers.writers():
            attach = getattr(writer, "attach_library", None)
            if callable(attach):
                attach(self.library_db)

    def _write_cell_summaries(self, results: Dict[str, SimulationResult]) -> None:
        grouped: Dict[str, List[SimulationResult]] = defaultdict(list)
        for result in results.values():
            grouped[result.job.cell_name].append(result)

        for cell, cell_results in grouped.items():
            cell_dir = cell_results[0].job.output_dir
            summary_dir = cell_dir / "simulation"
            summary_dir.mkdir(parents=True, exist_ok=True)
            summary_path = summary_dir / "summary.json"
            payload = {
                "engine": self.engine,
                "cell": cell,
                "jobs": [res.data for res in cell_results],
                "status": "completed" if all(res.is_success() for res in cell_results) else "partial",
            }
            summary_path.write_text(json.dumps(payload, indent=2))


# ----------------------------------------------------------------------
# Job builders
# ----------------------------------------------------------------------

def build_jobs_for_library(
    library_db: CellLibraryDB,
    generated_files: Dict[str, List[str]],
    simulation_root: Path | str | None = None,
) -> List[SimulationJob]:
    sim_root = Path(simulation_root) if simulation_root else None
    jobs: List[SimulationJob] = []
    try:
        analyzer_params = library_db.get_analyzer_params()
    except ConfigurationError:
        analyzer_params = {}
    mpw_bound = library_db.get_config_param("mpw_search_bound", None)
    for cell_name, file_paths in generated_files.items():
        cell = library_db.get_cell(cell_name)
        arc_prefixes = _build_arc_prefix_map(cell, library_db)
        for path_str in file_paths:
            deck_path = Path(path_str).resolve()
            sim_type = deck_path.parent.name
            cell_dir = (sim_root / cell_name) if sim_root else deck_path.parent.parent
            if sim_root:
                cell_dir.mkdir(parents=True, exist_ok=True)
                cell_dir = cell_dir.resolve()
            else:
                cell_dir = cell_dir.resolve()
            arc = _match_arc(deck_path.stem, arc_prefixes)
            metadata = {
                "cell": cell_name,
                "arc_id": deck_path.stem,
                "sim_type": sim_type,
            }
            if arc is not None:
                metadata.update({
                    "pin": arc.pin,
                    "related": arc.related_pin,
                    "timing_type": arc.timing_type,
                    "table_type": arc.table_type,
                })
                # Provide extra context for latch constraint optimization.
                metadata["cell_is_latch"] = bool(getattr(cell, "is_latch", False))
                try:
                    output_conditions = arc.get_condition_outputs(cell)
                except Exception:
                    output_conditions = dict(getattr(arc, "output_condition_dict", {}) or {})

                primary_output = None
                output_pins = list(cell.get_output_pins() or [])
                for out_pin in output_pins:
                    if out_pin in output_conditions:
                        primary_output = out_pin
                        break
                if primary_output is None and output_conditions:
                    primary_output = sorted(output_conditions.keys())[0]
                if primary_output is None and output_pins:
                    primary_output = output_pins[0]

                if primary_output:
                    metadata["primary_output"] = primary_output
                    if primary_output in output_conditions:
                        metadata["primary_output_init"] = output_conditions[primary_output]
                    try:
                        from zlibboost.simulation.polarity import resolve_output_pin

                        polarity = resolve_output_pin(cell, primary_output)
                        metadata["primary_output_is_negative"] = bool(
                            polarity is not None and polarity.is_negative
                        )
                    except Exception:
                        # Keep metadata best-effort; latch optimizer will assume non-inverting.
                        metadata["primary_output_is_negative"] = False
            metadata.update(analyzer_params)
            if mpw_bound is not None:
                metadata.setdefault("mpw_search_bound", mpw_bound)

            job_id = f"{cell_name}:{deck_path.stem}"
            job = SimulationJob(
                job_id=job_id,
                cell_name=cell_name,
                sim_type=sim_type,
                deck_path=deck_path,
                output_dir=cell_dir,
                arc=arc,
                metadata=metadata,
            )
            jobs.append(job)
    return jobs


def _build_arc_prefix_map(cell, library_db) -> Dict[str, List[TimingArc]]:
    mapping: Dict[str, List[TimingArc]] = defaultdict(list)
    for arc in cell.timing_arcs:
        try:
            generator = SpiceGeneratorFactory.get_generator(arc, cell, library_db)
        except ValueError:
            continue
        base_name = generator._build_base_filename()  # type: ignore[attr-defined]
        mapping[base_name].append(arc)
    return mapping


def _match_arc(filename_stem: str, arc_map: Dict[str, List[TimingArc]]) -> TimingArc | None:
    """Return the best matching TimingArc for a generated deck filename stem.

    Generated SPICE deck names are based on a *base filename* plus sweep suffixes
    (e.g. ``_i1_0``/``_i2_0``). Some arcs legitimately produce base filenames that
    are prefixes of other arcs (e.g. MPW arcs with/without condition vectors).

    """

    if not arc_map:
        return None

    matches: list[tuple[bool, int, str, list[TimingArc]]] = []
    for base, arcs in arc_map.items():
        if filename_stem == base:
            matches.append((True, len(base), base, arcs))
            continue
        if filename_stem.startswith(f"{base}_"):
            matches.append((False, len(base), base, arcs))

    if not matches:
        return None

    # Sort: exact matches first, then longest base (most specific) first.
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _is_exact, _length, _base, arcs = matches[0]

    # If multiple arcs share a base, return exact match on timing/table when encoded.
    if len(arcs) == 1:
        return arcs[0]

    for arc in arcs:
        if arc.timing_type in filename_stem and arc.table_type in filename_stem:
            return arc
    return arcs[0]


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------

def run_for_library(
    library_db: CellLibraryDB,
    output_dir: Path | str,
    engine: str = "mock",
    generated_files: Dict[str, List[str]] | None = None,
    only_types: Set[str] | Iterable[str] | None = None,
) -> Dict[str, Any]:
    """Generate decks (if necessary), run simulations, and return summary."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    threads = int(library_db.get_config_param("threads", 1) or 1)
    scheduler = SimulationScheduler(max_workers=max(1, threads))
    writer_registry = ResultWriterRegistry(
        [
            DelayResultWriter(library_db),
            ConstraintResultWriter(library_db),
            HiddenResultWriter(library_db),
            LeakageResultWriter(library_db),
            MpwResultWriter(library_db),
        ]
    )

    generated = generated_files or SpiceGeneratorFactory.generate_files_for_library(
        library_db, str(output_dir)
    )
    filtered = generated
    if only_types is not None:
        if isinstance(only_types, str):
            allowed = {only_types.lower()}
        else:
            allowed = {t.lower() for t in only_types}
        filtered = {}
        for cell_name, file_paths in generated.items():
            selected = [
                path for path in file_paths if Path(path).parent.name.lower() in allowed
            ]
            if selected:
                filtered[cell_name] = selected

    jobs = build_jobs_for_library(library_db, filtered, simulation_root=output_dir)

    if not jobs:
        raise ConfigurationError("No simulation jobs available for execution")

    orchestrator = SimulationOrchestrator(
        library_db=library_db,
        engine=engine,
        scheduler=scheduler,
        writers=writer_registry,
    )
    results = orchestrator.run(jobs)

    _ensure_cell_summaries(library_db, output_dir, results, engine)

    cell_summary = defaultdict(list)
    for result in results.values():
        cell_summary[result.job.cell_name].append(result.data)

    return {
        "engine": engine,
        "cells": dict(cell_summary),
        "job_count": len(results),
    }


def _ensure_cell_summaries(
    library_db: CellLibraryDB,
    output_dir: Path,
    results: Dict[str, SimulationResult],
    engine: str,
) -> None:
    present = {result.job.cell_name for result in results.values()}
    for cell_name in library_db.get_all_cell_names():
        cell_dir = Path(output_dir) / cell_name
        sim_dir = cell_dir / "simulation"
        sim_dir.mkdir(parents=True, exist_ok=True)
        summary_path = sim_dir / "summary.json"
        if cell_name not in present:
            payload = {
                "engine": engine,
                "cell": cell_name,
                "jobs": [],
                "status": "skipped",
            }
            summary_path.write_text(json.dumps(payload, indent=2))
        elif not summary_path.exists():
            payload = {
                "engine": engine,
                "cell": cell_name,
                "jobs": [res.data for res in results.values() if res.job.cell_name == cell_name],
                "status": "completed",
            }
            summary_path.write_text(json.dumps(payload, indent=2))
