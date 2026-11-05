#!/usr/bin/env python3
"""Post-outcome root diagnostics; never changes selections or the original family."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

try:
    from . import reproduce as base
except ImportError:
    import reproduce as base


def seed_for(namespace, label):
    return int(hashlib.sha256(f"{namespace}:{label}".encode()).hexdigest(), 16)


def validate_matrix(matrix, names, draws):
    x = np.asarray(matrix, dtype=float)
    base.require(x.ndim == 2 and x.shape[0] >= 3 and x.shape[1] == len(names),
                 "Expected at least three whole roots and one column per estimand")
    base.require(len(names) > 0 and len(names) == len(set(names)), "Invalid estimand names")
    base.require(np.isfinite(x).all() and draws > 0, "Nonfinite input or invalid draws")
    return x


def resampled_means(x, draws, seed, multiplier=False):
    """Every draw acts on the complete root vector across regimes and cells."""
    rng = np.random.default_rng(seed)
    n, p = x.shape
    result = np.empty((draws, p))
    mean = x.mean(axis=0)
    centered = x - mean
    for start in range(0, draws, 256):
        count = min(256, draws - start)
        if multiplier:
            # Conditional variance equals the sample variance of the root mean.
            result[start:start + count] = (
                mean + rng.standard_normal((count, n)) @ centered / math.sqrt(n * (n - 1)))
        else:
            indices = rng.integers(0, n, size=(count, n))
            result[start:start + count] = x[indices].mean(axis=1)
    return result


def bands(matrix, names, draws, seed, standardized=False, multiplier=False):
    x = validate_matrix(matrix, names, draws)
    mean = x.mean(axis=0)
    se = x.std(axis=0, ddof=1) / math.sqrt(len(x))
    delta = resampled_means(x, draws, seed, multiplier) - mean
    nonconstant = se > 0
    if standardized:
        maximum = (np.max(np.abs(delta[:, nonconstant] / se[nonconstant]), axis=1)
                   if nonconstant.any() else np.zeros(draws))
    else:
        maximum = np.max(np.abs(delta), axis=1)
    critical = float(np.sort(maximum)[math.ceil(.95 * draws) - 1])
    width = critical * se if standardized else np.full(len(names), critical)
    return {
        "roots": len(x), "family_size": len(names), "draws": draws,
        "critical_value": critical,
        "standardization": "fixed original sample SE" if standardized else "none; bps",
        "resampling": "Gaussian root multipliers" if multiplier else "whole-root pairs",
        "zero_empirical_se": [names[i] for i in range(len(names)) if not nonconstant[i]],
        "estimates": {name: {"mean": float(mean[i]), "se": float(se[i]),
                             "lower": float(mean[i] - width[i]),
                             "upper": float(mean[i] + width[i])}
                      for i, name in enumerate(names)},
    }


def leave_one_root_out(matrix, names, roots, draws, namespace):
    x = validate_matrix(matrix, names, draws)
    base.require(len(roots) == len(x) and len(set(roots)) == len(roots), "Invalid root IDs")
    results = []
    for i, root in enumerate(roots):
        reduced = np.delete(x, i, axis=0)
        result = bands(reduced, names, draws, seed_for(namespace, f"leave-out-{root}"))
        results.append({"omitted_root": root, **result})
    return results


def compare_reference(actual, expected, path="report"):
    if isinstance(expected, dict):
        base.require(isinstance(actual, dict) and actual.keys() == expected.keys(), path)
        for key in expected:
            compare_reference(actual[key], expected[key], path + "/" + key)
    elif isinstance(expected, list):
        base.require(isinstance(actual, list) and len(actual) == len(expected), path)
        for i, (a, b) in enumerate(zip(actual, expected)):
            compare_reference(a, b, path + f"/{i}")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        base.close(actual, expected, path)
    else:
        base.require(actual == expected, path)


def calculate(directory, spec):
    base.verify_inputs(directory)
    base.require(spec["input_sha256"] == hashlib.sha256(
        (directory / "market_observations.csv").read_bytes()).hexdigest(),
        "Diagnostic specification binds a different observation file")
    base.require(spec["evidence_class"] == "post-outcome diagnostic", "Wrong scope")
    base.require(spec["family"] == "original24" and spec["draws"] == 20000,
                 "Changed diagnostic family or draw count")
    cells, selections, _ = base.load_market(directory / "market_observations.csv")
    vectors = []
    for root in base.ROOTS:
        names, vector = base.original_contrasts(
            {(g, v, s): cells[root, g, v, s][0]
             for g in base.REGIMES for v in (0, 1) for s in base.SCALES})
        vectors.append(vector)
    x = np.asarray(vectors)
    expected = base.read_json(directory / "expected.json")
    original = base.simultaneous_band(x, names, expected["market"]["bootstrap_seed_sha256"])
    base.check_estimates(original, expected["market"], "original24 before robustness")
    draws, namespace = spec["draws"], spec["seed_namespace"]
    methods = {
        "pairs_maxabs_seed_a": bands(x, names, draws, seed_for(namespace, "pairs-a")),
        "pairs_maxabs_seed_b": bands(x, names, draws, seed_for(namespace, "pairs-b")),
        "pairs_fixed_se_max": bands(x, names, draws, seed_for(namespace, "pairs-a"), True),
        "gaussian_fixed_se_max": bands(x, names, draws, seed_for(namespace, "gaussian"), True, True),
    }
    omissions = leave_one_root_out(x, names, list(base.ROOTS), draws, namespace)
    largest, distributions = {}, {}
    for g in base.REGIMES:
        for v in (0, 1):
            name = f"cell:{g}:rho{v}:0.3"
            j = names.index(name)
            values = x[:, j]
            deleted_means = [row["estimates"][name]["mean"] for row in omissions]
            deleted_upper = [row["estimates"][name]["upper"] for row in omissions]
            largest[name] = {
                "mean": float(values.mean()),
                "loo_mean_min": min(deleted_means), "loo_mean_max": max(deleted_means),
                "loo_upper_max": max(deleted_upper),
                "loo_negative_means": sum(value < 0 for value in deleted_means),
                "loo_negative_upper_bands": sum(value < 0 for value in deleted_upper),
                "max_absolute_mean_change": max(abs(value - values.mean()) for value in deleted_means),
                "alternative_upper_max": max(row["estimates"][name]["upper"] for row in methods.values()),
            }
            distributions[name] = {
                "quantiles_0_25_50_75_100": np.quantile(values, [0, .25, .5, .75, 1]).tolist(),
                "negative_roots": int(np.sum(values < -base.TOL)),
                "positive_roots": int(np.sum(values > base.TOL)),
                "near_zero_roots": int(np.sum(np.abs(values) <= base.TOL)),
                "no_update_roots": sum(not selections[root, g][2] for root in base.ROOTS),
            }
    report = {
        "status": "completed-post-outcome-diagnostics", "spec": spec,
        "market_input_sha256": hashlib.sha256((directory / "market_observations.csv").read_bytes()).hexdigest(),
        "original24_reproduced": original, "alternative_bands": methods,
        "leave_one_root_out": omissions, "largest_scale": largest,
        "root_distributions": distributions,
        "coverage_scope": "Each method/deletion treats the same 24 columns jointly. No joint guarantee across methods or deletions; outcome-aware diagnostics.",
        "zero_se_scope": "Constant observed columns do not prove zero population variation; standardized degenerate intervals are not a positive-prefix certificate.",
        "new_selections": 0, "new_simulations": 0,
    }
    return report, names, x


def write_outputs(output, report, names, matrix, plots):
    output.mkdir(parents=True, exist_ok=True)
    base.write_json(output / "root_robustness.json", report)
    with (output / "root_effects.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["root_id", *names])
        writer.writerows([[root, *values] for root, values in zip(base.ROOTS, matrix)])
    with (output / "leave_one_root_out.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["omitted_root", "estimand", "mean_bps", "lower_bps", "upper_bps"])
        for omission in report["leave_one_root_out"]:
            for name, row in omission["estimates"].items():
                writer.writerow([omission["omitted_root"], name, row["mean"], row["lower"], row["upper"]])
    lines = [r"\subsection{Construction and deletion results}",
             r"\label{app:root-robustness}",
             "These checks reuse the frozen selections and 100 bps utility after the original outcomes were inspected. They neither add independent roots nor extend the original confirmatory family. Each method resamples the complete root vector across both regimes and all 24 estimands.",
             "",
             r"\begin{table}[h]\centering\small",
             r"\begin{tabular}{llrrr}\toprule",
             r"Regime & $\rho$ & LOO mean range & Max. LOO upper & Max. alternative upper\\\midrule"]
    for name, row in report["largest_scale"].items():
        g = "Liquid" if "liquid_market" in name else "Thin"
        v = name.split(":rho")[1].split(":")[0]
        lines.append(f"{g} & {v} & [{row['loo_mean_min']:.2f}, {row['loo_mean_max']:.2f}] & {row['loo_upper_max']:.2f} & {row['alternative_upper_max']:.2f}" + r"\\")
    lines += [r"\bottomrule\end{tabular}",
              r"\caption{Largest scale $s=0.30$: all values are bps. Leave-one-root-out (LOO) checks refit a 24-estimate unstandardized maximum-deviation band using 49 shared roots and 20,000 draws for each of 50 deletions. Alternative bounds use two independently seeded paired-root runs, a fixed-sample-SE standardized paired-root maximum, and a standardized Gaussian root-multiplier maximum, each with 20,000 draws. No joint coverage is claimed across methods or deletions.}\label{tab:root-robustness}\end{table}",
              "",
              "Standardization divides bootstrap deviations by the original sample standard error, not a reestimated standard error in each draw. Gaussian multipliers approximate the centered root-mean distribution using its empirical covariance. Constant observed columns are flagged; a zero empirical standard error does not establish zero population uncertainty. Numerical bands remain approximate and conditional on the frozen synthetic world.",
              "",
              r"\begin{figure}[h]\centering\includegraphics[width=.95\linewidth]{market_root_distribution.pdf}",
              r"\caption{Fifty root-level procedure gains at the largest scale under the original 100 bps utility. Each point averages four paired deployments; lines connect the same root across response settings. Incumbent-retaining roots contribute zero. Diamonds and bars show the original full-cohort means and 24-estimate simultaneous bands, not uncertainty for individual roots.}\label{fig:root-distribution}\end{figure}"]
    (output / "root_robustness.tex").write_text("\n".join(lines) + "\n")
    if plots:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.1), sharey=True)
        jitter = np.linspace(-.12, .12, len(base.ROOTS))
        for ax, g, title in zip(axes, base.REGIMES, ["Liquid", "Thin"]):
            y = [matrix[:, names.index(f"cell:{g}:rho{v}:0.3")] for v in (0, 1)]
            for i in range(len(base.ROOTS)):
                ax.plot([jitter[i], 1 + jitter[i]], [y[0][i], y[1][i]], color="0.75", lw=.45, alpha=.5, zorder=1)
            for v, color, marker in [(0, "#0072B2", "o"), (1, "#D55E00", "^")]:
                ax.scatter(v + jitter, y[v], s=13, color=color, marker=marker, alpha=.7, zorder=2)
                old = report["original24_reproduced"]["estimates"][f"cell:{g}:rho{v}:0.3"]
                ax.errorbar(v + .22, old["estimate_bps"], yerr=old["upper_bps"] - old["estimate_bps"], fmt="D", color="black", ms=4, capsize=3, lw=1.1, zorder=3)
            ax.axhline(0, color="0.35", lw=.7, ls="--")
            ax.set(xticks=[0, 1], xticklabels=[r"$\rho=0$", r"$\rho=1$"], title=title + " (50 shared roots)", xlim=(-.3, 1.45))
            ax.spines[["top", "right"]].set_visible(False)
        axes[0].set_ylabel("Root-mean deployment gain (bps)")
        fig.tight_layout()
        fig.savefig(output / "market_root_distribution.pdf", metadata={"Author": "", "Title": "Root-level deployment gains"})
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(__file__).parent / "data")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    spec = base.read_json(args.data / "root_robustness_spec.json")
    report, names, matrix = calculate(args.data, spec)
    if args.expected:
        compare_reference(report, base.read_json(args.expected))
    write_outputs(args.output, report, names, matrix, not args.no_plots)
    print(json.dumps({"status": report["status"], "largest_scale": report["largest_scale"],
                      "reference_checked": bool(args.expected)}))


if __name__ == "__main__":
    main()
