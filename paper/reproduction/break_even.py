#!/usr/bin/env python3
"""Outcome-aware, fixed-selection completion-utility diagnostic.

The confidence set projects an eight-component bootstrap rectangle. It does
not divide confidence endpoints blindly or delete unstable ratio draws.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

try:
    from . import reproduce as base
    from .root_robustness import compare_reference
except ImportError:
    import reproduce as base
    from root_robustness import compare_reference


def project_nonnegative_zero(a_interval, b_interval):
    """Return {p >= 0: some (a,b) in the rectangle satisfies a+p*b=0}.

    For p >= 0 the possible values are [a_low+p*b_low,a_high+p*b_high].
    Intersect the two linear inequalities with [0,infinity). Null endpoints
    represent infinity only when kind is unbounded; empty is explicit.
    """
    a0, a1 = map(float, a_interval)
    b0, b1 = map(float, b_interval)
    if not np.isfinite([a0, a1, b0, b1]).all() or a0 > a1 or b0 > b1:
        raise ValueError("Invalid component interval")
    lower, upper = 0.0, float("inf")
    for c, slope in ((a0, b0), (-a1, -b1)):
        if slope > 0:
            upper = min(upper, -c / slope)
        elif slope < 0:
            lower = max(lower, -c / slope)
        elif c > 0:
            return {"kind": "empty", "lower_bps": None, "upper_bps": None}
    if upper < lower:
        return {"kind": "empty", "lower_bps": None, "upper_bps": None}
    return {"kind": "bounded" if np.isfinite(upper) else "unbounded",
            "lower_bps": lower, "upper_bps": upper if np.isfinite(upper) else None}


def component_bootstrap(matrix, *, draws, seed, confidence):
    """One root index draw shared across every component and condition."""
    x = np.asarray(matrix, dtype=float)
    if x.ndim != 2 or x.shape[0] < 2 or not np.isfinite(x).all():
        raise ValueError("Finite independent root vectors required")
    if draws < 100 or not 0 < confidence < 1:
        raise ValueError("Invalid bootstrap configuration")
    mean = x.mean(axis=0)
    se = x.std(axis=0, ddof=1) / np.sqrt(len(x))
    if np.any(se == 0):
        raise ValueError("Constant empirical components do not identify population uncertainty")
    rng = np.random.Generator(np.random.PCG64(seed))
    boot = np.empty((draws, x.shape[1]))
    for start in range(0, draws, 256):
        indices = rng.integers(0, len(x), (min(256, draws-start), len(x)))
        boot[start:start+len(indices)] = x[indices].mean(axis=1)
    maxima = np.max(np.abs(boot-mean) / se, axis=1)
    q = float(np.quantile(maxima, confidence))
    return mean, se, q, boot


def ratio_summary(a, b, draws_a, draws_b, confidence):
    zero = int(np.count_nonzero(draws_b == 0))
    flips = int(np.count_nonzero(draws_b * b < 0)) if b else None
    stable = b != 0 and zero == 0 and flips == 0
    interval = None
    if stable:
        alpha = 1-confidence
        # All draws are included. Do not clip negative mathematical thresholds.
        interval = np.quantile(-draws_a/draws_b, [alpha/2, 1-alpha/2]).tolist()
    return {"point_bps": float(-a/b) if b else None,
            "zero_denominator_draws": zero, "opposite_sign_denominator_draws": flips,
            "percentile_pointwise_bps": interval,
            "percentile_status": "reported-all-draws" if stable else "omitted-unstable-denominator"}


def calculate(directory, spec):
    base.require(spec["schema"] == "fixed-selection-break-even-diagnostic-v1"
                 and spec["outcome_aware"] is True, "Wrong diagnostic scope")
    base.require(spec["roots"] == list(base.ROOTS) and spec["scale"] == .3
                 and spec["family_size"] == 8 and spec["selection_utility_bps"] == 100
                 and spec["replicates_per_root_cell"] == 4, "Changed diagnostic population")
    cells, _, _ = base.load_market(directory / "market_observations.csv")
    labels = [f"{g}:rho{rho}" for g in base.REGIMES for rho in (0, 1)]
    base.require(labels == spec["cells"], "Changed diagnostic family")
    x = np.array([[v for g in base.REGIMES for rho in (0, 1)
                   for v in cells[r, g, rho, .3][1:]] for r in base.ROOTS])
    mean, se, q, boot = component_bootstrap(x, draws=spec["draws"], seed=spec["seed"],
                                          confidence=spec["confidence"])
    rows = {}
    for j, name in enumerate(labels):
        i = 2*j
        a, b = mean[i:i+2]
        ai = [float(a-q*se[i]), float(a+q*se[i])]
        bi = [float(b-q*se[i+1]), float(b+q*se[i+1])]
        rows[name] = {
            "shortfall_gain_bps": float(a), "unfilled_fraction_gain": float(b),
            "unfilled_difference_pp": float(100*b),
            "a_joint_interval_bps": ai, "b_joint_interval_fraction": bi,
            "b_interval_contains_zero": bi[0] <= 0 <= bi[1],
            "break_even": ratio_summary(a, b, boot[:,i], boot[:,i+1], spec["confidence"]),
            "nonnegative_joint_confidence_set": project_nonnegative_zero(ai, bi),
            "gain_at_100_bps": float(a+100*b),
        }
    report = {"status": "completed-post-outcome-break-even-diagnostic",
              "root_clusters": len(x), "family_size": 8, "draws": spec["draws"],
              "seed": spec["seed"], "confidence": spec["confidence"],
              "fixed_se_max_critical_value": q, "cells": rows,
              "analysis_spec": spec,
              "data_sha256": hashlib.sha256((directory/"market_observations.csv").read_bytes()).hexdigest(),
              "new_selections": 0, "discarded_bootstrap_draws": 0}
    return report, x


def write_outputs(output, report, matrix):
    output.mkdir(parents=True, exist_ok=True)
    base.write_json(output/"break_even.json", report)
    with (output/"root_components.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["root_id", "condition", "shortfall_gain_bps", "unfilled_fraction_gain"])
        for root, row in zip(base.ROOTS, matrix):
            for j, label in enumerate(report["cells"]):
                writer.writerow([root, label, row[2*j], row[2*j+1]])
    lines = [r"\begin{table}[t]\centering\small",
             r"\begin{tabular}{@{}lrrrrl@{}}\toprule",
             r"Regime & $\rho$ & $\bar a$ (bps) & $100\bar b$ (pp) & $\widehat p^*$ (bps) & Joint set, $p\geq0$ (bps)\\\midrule"]
    for label, row in report["cells"].items():
        regime, rho = label.split(":rho")
        c = row["nonnegative_joint_confidence_set"]
        if c["kind"] == "empty": interval = r"$\varnothing$"
        elif c["kind"] == "unbounded": interval = rf"$[{c['lower_bps']:.2f},\infty)$"
        else: interval = rf"$[{c['lower_bps']:.2f},{c['upper_bps']:.2f}]$"
        point = row["break_even"]["point_bps"]
        point_text = "undefined" if point is None else f"{point:.3f}"
        lines.append(f"{regime.replace('_market','').title()} & {rho} & "
                     f"{row['shortfall_gain_bps']:.4f} & {row['unfilled_difference_pp']:.4f} & "
                     f"{point_text} & {interval}" + r"\\")
    lines += [r"\bottomrule\end{tabular}",
              r"\caption{Largest-scale completion-utility diagnostic with original choices fixed. The threshold is a ratio of mean components, $\widehat p^*=-\bar a/\bar b$, computed before rounding. The sets project an approximate simultaneous 95\% bootstrap rectangle for all eight component means, using 20,000 shared-root draws. This separate, outcome-aware family does not modify the original 24 or diagnostic 64 estimates.}\label{tab:break-even}",
              r"\end{table}"]
    (output/"break_even.tex").write_text("\n".join(lines)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(__file__).parent/"data")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected", type=Path)
    args = parser.parse_args()
    base.verify_inputs(args.data)
    spec = base.read_json(args.data/"break_even_spec.json")
    report, matrix = calculate(args.data, spec)
    if args.expected:
        compare_reference(report, base.read_json(args.expected))
    write_outputs(args.output, report, matrix)
    print(json.dumps({"status": report["status"], "break_even_reference_checked": bool(args.expected)}))


if __name__ == "__main__":
    main()
