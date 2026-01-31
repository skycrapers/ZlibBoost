"""Deck preprocessing utilities for ngspice compatibility.

Legacy flows expected ngspice to emit HSPICE-style ``.mt0`` reports.  The
preprocessor rewrites every ``.sp`` deck to inject ngspice control blocks that
replicate that behaviour and generates deterministic measurement files so the
modern pipeline can keep parsing with the existing HSPICE parsers.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List

from zlibboost.core.logger import get_logger

logger = get_logger(__name__)


def preprocess_deck_tree(target: str | Path) -> None:
    """Rewrite all ``.sp`` decks below *target* for ngspice execution."""

    path = Path(target).expanduser()
    if not path.exists():
        logger.warning("Ngspice preprocess target does not exist: %s", path)
        return

    if path.is_file():
        if path.suffix.lower() == ".sp":
            _process_file(path)
        else:
            logger.debug("Skip non-SP deck during ngspice preprocess: %s", path)
        return

    for deck_path in sorted(path.rglob("*.sp")):
        _process_file(deck_path)


def _process_file(sp_path: Path) -> None:
    sp_path = sp_path.resolve()
    logger.debug("Preprocessing ngspice deck: %s", sp_path)
    mt0_path = sp_path.with_suffix(".mt0")

    try:
        content = sp_path.read_text()
    except OSError as exc:
        logger.error("Failed to read deck %s: %s", sp_path, exc)
        return

    # Skip if already preprocessed (contains .control block)
    if ".control" in content:
        logger.debug("Deck already preprocessed, skipping: %s", sp_path)
        return

    try:
        processed = _transform_spice_content(content, sp_path, mt0_path)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to transform deck %s: %s", sp_path, exc)
        return

    try:
        sp_path.write_text(processed)
    except OSError as exc:
        logger.error("Failed to write transformed deck %s: %s", sp_path, exc)
    else:
        logger.debug("Ngspice deck rewritten successfully: %s", sp_path)


def _transform_spice_content(file_content: str, sp_path: Path, mt0_path: Path) -> str:
    meas_lines: List[str] = []
    remaining_lines: List[str] = []
    tend_lines: List[str] = []
    meas_params: List[str] = []
    cap_params: dict[str, str] = {}
    temp_line: List[str] = []
    file_first_alter_content = file_content.split(".alter")[0]

    for line in file_first_alter_content.splitlines():
        if line.startswith(".param"):
            temp_line.append(line)

    in_meas_block = False
    for line in file_content.splitlines():
        stripped = line.strip()
        if stripped.startswith(".meas"):
            in_meas_block = True
            meas_lines.append(line)
        elif in_meas_block and stripped.startswith("+"):
            meas_lines[-1] += " " + stripped[1:].strip()
        elif in_meas_block and stripped == "":
            in_meas_block = False
        elif in_meas_block and not stripped.startswith("+"):
            in_meas_block = False
            remaining_lines.append(line)
        else:
            if stripped.startswith(".param"):
                param_match = re.match(r"\.param\s+(\w+)\s*=\s*(.*)", stripped, re.IGNORECASE)
                if param_match:
                    param_name = param_match.group(1)
                    param_value = param_match.group(2)
                    if param_name.endswith("_tend"):
                        tend_lines.append(line)
                    elif param_name.endswith("_cap"):
                        cap_params[param_name] = param_value
            remaining_lines.append(line)

    modified_meas_lines: List[str] = []
    for meas_line in meas_lines:
        modified_line = meas_line.strip()[1:]
        modified_line = modified_line.replace("from=", "from=$&").replace("to=", "to=$&")
        modified_line = re.sub(r"from=\$&'(\w+)'", r"from=$&\1", modified_line)
        modified_line = re.sub(r"to=\$&'(\w+)'", r"to=$&\1", modified_line)
        param_match = re.search(r"(\w+)\s+PARAM='(.*?)'", modified_line)
        if param_match:
            modified_line = f"let {param_match.group(1)}='{param_match.group(2)}'"
            meas_params.append(param_match.group(1))
        else:
            match = re.search(r"meas\s+\w+\s+(\w+)", modified_line)
            if match:
                meas_params.append(match.group(1))
        modified_meas_lines.append(modified_line)

    remaining_content = "\n".join(remaining_lines)

    tend_lines = list(set(tend_lines))
    tran_tend_lines = [line for line in tend_lines if re.match(r"\.param\s+tran_tend\s*=", line)]
    other_tend_lines = [line for line in tend_lines if not re.match(r"\.param\s+tran_tend\s*=", line)]
    tend_lines = tran_tend_lines + other_tend_lines
    modified_tend_lines = [line.replace(".param", "let", 1) for line in tend_lines]
    modified_cap_lines = [f"let {name}={value}" for name, value in cap_params.items()]

    final_lines: List[str] = []
    alter_found = False
    alter_count = 0
    has_alter_blocks = any(line.strip().startswith(".alter") for line in remaining_content.splitlines())
    treat_next_line_as_alter = False

    for idx, line in enumerate(remaining_content.splitlines()):
        stripped = line.strip()
        if stripped.startswith(".tran"):
            final_lines.append(".tran 1.00e-11 'tran_tend'")
            treat_next_line_as_alter = False
            continue

        if treat_next_line_as_alter:
            treat_next_line_as_alter = False
            alter_found = True
            alter_count += 1
            final_lines.append(".control")
            if modified_cap_lines:
                final_lines.extend(modified_cap_lines)
            final_lines.extend(modified_tend_lines)
            for temp in temp_line:
                final_lines.append(temp.replace(".param", "let"))
            final_lines.append("run")
            final_lines.extend(modified_meas_lines)
            final_lines.extend(_generate_echo_statements(meas_params, mt0_path, alter_count))
            continue

        if stripped.startswith(".alter"):
            has_alter_blocks = True
            alter_found = True
            alter_count += 1
            if alter_count == 1:
                final_lines.append(".control")
                if modified_cap_lines:
                    final_lines.extend(modified_cap_lines)
                final_lines.extend(modified_tend_lines)
                for temp in temp_line:
                    final_lines.append(temp.replace(".param", "let"))
                final_lines.append("run")
                final_lines.extend(modified_meas_lines)
                final_lines.extend(_generate_echo_statements(meas_params, mt0_path, alter_count))
            else:
                final_lines.append("reset")
                final_lines.append("run")
                final_lines.extend(modified_meas_lines)
                final_lines.extend(_generate_echo_statements(meas_params, mt0_path, alter_count))
            continue

        if stripped.startswith(".option"):
            final_lines.append(
                ".option numdgt=6 measdgt=6 ingold=2 save=nooutput method=gear "
                "gmin=1e-15 gminfloatdefault=gmindc redefinedparams=ignore "
                "rabsshort=1m limit=delta save=nooutput"
            )
            continue

        if stripped.startswith(".param"):
            if alter_found:
                final_lines.append(line.replace(".param", "alterparam"))
                final_lines.append(line.replace(".param", "let"))
            else:
                final_lines.append(line)
            continue

        if stripped.startswith("simulator"):
            final_lines.append("")
            continue

        if stripped.startswith(".end"):
            if has_alter_blocks:
                if alter_count > 0:
                    alter_count += 1
                    final_lines.append("reset")
                    final_lines.append("run")
                    final_lines.extend(modified_meas_lines)
                    final_lines.extend(_generate_echo_statements(meas_params, mt0_path, alter_count))
                    if modified_cap_lines:
                        final_lines.extend(modified_cap_lines)
            else:
                final_lines.append(".control")
                if modified_cap_lines:
                    final_lines.extend(modified_cap_lines)
                final_lines.extend(modified_tend_lines)
                for temp in temp_line:
                    final_lines.append(temp.replace(".param", "let"))
                final_lines.append("run")
                final_lines.extend(modified_meas_lines)
                final_lines.extend(_generate_echo_statements(meas_params, mt0_path, 1))
            final_lines.append(".endc")
            final_lines.append(line)
            continue

        final_lines.append(line)

    final_content = "\n".join(final_lines)
    logger.debug("Ngspice deck processed: %s", sp_path)
    return final_content


def _generate_echo_statements(meas_params: Iterable[str], mt0_path: Path, alter_num: int) -> List[str]:
    echo_lines: List[str] = []
    params = list(meas_params)
    mt0_target = Path(mt0_path).name  # write measurements into simulator workdir

    if alter_num == 1:
        echo_lines.append(
            f'echo > "{mt0_target}" "\\$DATA1 SOURCE=\'Ngspice\' VERSION=\'R-2025.01 linux64\' PARAM_COUNT=0"'
        )
        echo_lines.append(f'echo >> "{mt0_target}" ".TITLE \'**** * Simulator language for Ngspice\'"')
        param_lines = [" ".join(params[i : i + 5]) for i in range(0, len(params), 5)]
        for line in param_lines:
            echo_lines.append(f'echo >> "{mt0_target}" "{line.lower()}"')

    if alter_num == 1:
        echo_lines.append(f'echo >> "{mt0_target}" "temper           alter#"')

    for i in range(0, len(params), 5):
        group = params[i : i + 5]
        value_line = " ".join(f"$&{param}" for param in group).strip()
        echo_lines.append(f'echo >> "{mt0_target}" "{value_line}"')

    echo_lines.append(f'echo >> "{mt0_target}" "25.00000         {alter_num}"')
    return echo_lines
