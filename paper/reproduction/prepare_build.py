#!/usr/bin/env python3
"""Assemble manuscript build inputs from freshly checked numeric outputs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil

TABLES = ("market_largest.tex", "all24.tex", "penalty_table.tex", "components.tex",
          "planner_table.tex", "proxy_deployment_gap.tex")
FIGURES = ("market_scale.pdf", "penalty_sensitivity.pdf", "planner_prefix.pdf")


def assemble(package: Path, output: Path) -> Path:
    package, output = package.resolve(), output.resolve()
    if output == package or output.is_relative_to(package) or package.is_relative_to(output):
        raise ValueError("Build output must be separate from the source package")
    report = json.loads((output / "report.json").read_text())
    roots = json.loads((output / "root-robustness/root_robustness.json").read_text())
    break_even = json.loads((output / "break-even/break_even.json").read_text())
    if (report["status"] != "passed-saved-outcome-reanalysis"
            or roots["status"] != "completed-post-outcome-diagnostics"
            or break_even["status"] != "completed-post-outcome-break-even-diagnostic"):
        raise ValueError("Checked numeric outputs are required before building")
    work = output / "paper-source"
    pairs = [(package / name, work / name) for name in ("main.tex", "supplement.tex", "references.bib")]
    pairs += [(package / "style" / name, work / "style" / name) for name in ("tmlr.sty", "tmlr.bst", "fancyhdr.sty", "LICENSE")]
    pairs += [(output / "generated" / name, work / "generated" / name) for name in TABLES]
    pairs += [(output / name, work / "figures" / name) for name in FIGURES]
    pairs += [(output / "root-robustness/root_robustness.tex", work / "generated/root_robustness.tex"),
              (output / "root-robustness/market_root_distribution.pdf", work / "figures/market_root_distribution.pdf"),
              (output / "break-even/break_even.tex", work / "generated/break_even.tex")]
    if any(not src.is_file() for src, _ in pairs):
        raise ValueError("Missing generated table, figure, or manuscript source")
    hashes = {}
    for src, dst in pairs:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        hashes[dst.relative_to(work).as_posix()] = hashlib.sha256(dst.read_bytes()).hexdigest()
    (output / "build-inputs.json").write_text(json.dumps({
        "numeric_report_sha256": hashlib.sha256((output / "report.json").read_bytes()).hexdigest(),
        "tables_and_figures": "freshly recomputed output, not staged package figures",
        "files": hashes}, indent=2) + "\n")
    return work


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(assemble(args.package, args.output))
