from __future__ import annotations

import os
import sys
import argparse
from typing import Dict

from zlibboost.cli.pipeline import PipelineConfig, run_pipeline
from zlibboost.core.logger import LogManager, LOG_LEVELS
from zlibboost.core.exceptions import ZlibBoostError

BANNER = r"""
  ______ _ _     ____                  _   
 |__  / (_) |__ | __ )  ___   ___  ___| |_ 
   / /| | | '_ \|  _ \ / _ \ / _ \/ __| __|
  / /_| | | |_) | |_) | (_) | (_) \__ \ |_ 
 /____|_|_|_.__/|____/ \___/ \___/|___/\__|                                  
"""

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zlibboost")
    p.add_argument(
        "-c",
        "--config",
        action="append",
        default=[],
        help="Config TCL file (repeatable). Template files referenced inside the config will be auto-detected.",
    )
    p.add_argument(
        "--simulate",
        dest="simulate",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Run simulations after deck generation. Use --no-simulate to skip.",
    )
    return p


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}

def _print_banner() -> None:
    print(BANNER.rstrip("\n"))
    print()


def main(argv: list[str] | None = None) -> int:
    _print_banner()
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.config:
        parser.error("At least one -c/--config must be provided.")

    # Initialize logger
    log_level_name = os.environ.get("ZLIBBOOST_LOG_LEVEL", "INFO").upper()
    level = LOG_LEVELS.get(log_level_name, LOG_LEVELS["INFO"])
    LogManager().setup(log_level=level)
    logger = LogManager().get_logger("zlibboost.cli")

    overrides: Dict[str, str] = {}
    sim_engine = os.environ.get("ZLIBBOOST_SIM_ENGINE")
    if sim_engine is not None:
        sim_engine = sim_engine.strip() or None
    simulate_flag = args.simulate
    if simulate_flag is None:
        simulate_flag = _env_flag("ZLIBBOOST_SIMULATE", True)
    auto_arc_flag = _env_flag("ZLIBBOOST_AUTO_ARC", True)

    cfg = PipelineConfig(
        config_files=args.config,
        timing_files=[],
        out_dir=None,
        auto_arc=auto_arc_flag,
        overrides=overrides,
        simulate=simulate_flag,
        simulate_engine=sim_engine,
    )

    try:
        result = run_pipeline(cfg)
        # Summarize
        files = result.get("generated_files", {})
        total = sum(len(v) for v in files.values())
        logger.info(f"Generated {total} files for {len(files)} cells")
        # Human-readable stdout
        print("Generated files:")
        for cell, lst in files.items():
            print(f"  {cell}: {len(lst)} files")

        simulation = result.get("simulation")
        if simulation:
            sim_jobs = simulation.get("job_count", 0)
            engine = simulation.get("engine", cfg.simulate_engine or "unknown")
            print(f"Simulated decks: {sim_jobs} jobs via {engine}")
        else:
            print("Simulated decks: 0 (simulation disabled)")
        return 0
    except ZlibBoostError as e:
        logger.error(f"zlibboost error: {e}")
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        logger.error(f"unexpected error: {e}")
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
