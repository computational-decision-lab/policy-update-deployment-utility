#!/usr/bin/env python3
"""Offline reanalysis of the released, saved observations. No simulator or API."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys

import numpy as np

REGIMES = ("liquid_market", "thin_market")
SCALES = (0.002, 0.05, 0.3)
ROOTS = tuple(range(8101, 8151))
PENALTIES = (25, 50, 100, 200)
TOL = 1e-9


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(actual, expected, name):
    require(math.isfinite(actual) and math.isfinite(expected)
            and abs(actual - expected) <= TOL, f"Numerical mismatch: {name}")


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def verify_inputs(directory):
    provenance = read_json(directory / "provenance.json")
    for name, expected in provenance["files"].items():
        path = directory / name
        require(path.is_file(), f"Missing input: {name}")
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                f"Changed input: {name}")
    return provenance


def summarize_decisions(gains, adopted):
    """One value per independent selection unit; abstentions stay in the mean."""
    require(len(gains) == len(adopted) > 0, "Decision arrays must align")
    require(all(math.isfinite(x) for x in gains), "Nonfinite decision gain")
    require(all(a or g == 0 for a, g in zip(adopted, gains)),
            "No-update decisions must have exact zero gain")
    selected = [g for g, a in zip(gains, adopted) if a]
    return {
        "procedure_mean": sum(gains) / len(gains),
        "decision_units": len(gains),
        "no_update_units": len(gains) - len(selected),
        "reversals": sum(g < -TOL for g in selected),
        "selected_denominator": len(selected),
        "irr": sum(g < -TOL for g in selected) / len(selected) if selected else None,
        "irr_scope": "descriptive; excluded from simultaneous mean family",
    }


def positive_prefix(scales, intervals):
    """Contiguous tested prefix only; later positive cells cannot bridge a gap."""
    require(len(scales) == len(intervals), "Grid and intervals must align")
    require(list(scales) == sorted(set(scales)), "Grid must be ordered and unique")
    for lo, hi in intervals:
        require(math.isfinite(lo) and math.isfinite(hi) and lo <= hi, "Invalid band")
    prefix = []
    for scale, (lo, _) in zip(scales, intervals):
        if lo <= TOL:
            break
        prefix.append(scale)
    return prefix


def simultaneous_band(vectors, names, seed_sha256, draws=20000):
    """Resample shared roots jointly across the declared family."""
    matrix = np.asarray(vectors, dtype=float)
    require(matrix.ndim == 2 and matrix.shape[0] >= 2
            and matrix.shape[1] == len(names) and len(names) == len(set(names)),
            "Invalid root-by-estimand matrix")
    require(np.isfinite(matrix).all() and draws > 0, "Invalid bootstrap inputs")
    n = matrix.shape[0]
    mean = np.asarray([sum(matrix[:, j]) / n for j in range(len(names))])
    rng = random.Random(int(seed_sha256, 16))
    radii = []
    for start in range(0, draws, 256):
        indices = np.asarray([[rng.randrange(n) for _ in range(n)]
                              for _ in range(min(256, draws - start))])
        values = matrix[indices].mean(axis=1)
        radii.extend(np.max(np.abs(values - mean), axis=1).tolist())
    radius = sorted(radii)[math.ceil(.95 * draws) - 1]
    return {
        "root_clusters": n, "family_size": len(names), "bootstrap_draws": draws,
        "seed_sha256": seed_sha256, "joint_radius_bps": radius,
        "coverage": "approximate simultaneous 95%; conditional on frozen design",
        "estimates": {
            name: {"estimate_bps": float(mean[j]), "lower_bps": float(mean[j] - radius),
                   "upper_bps": float(mean[j] + radius)}
            for j, name in enumerate(names)
        },
    }


def load_market(path):
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    expected = {(r, g, v, s, k) for r in ROOTS for g in REGIMES
                for v in (0, 1) for s in SCALES for k in range(4)}
    grouped, keys, selection = {}, set(), {}
    for row in rows:
        root, rho, scale, rep = (int(row["root_id"]), int(row["response_value"]),
                                float(row["deployment_scale"]), int(row["replicate"]))
        require(int(row["search_pressure"]) == 16 and int(row["seed"]) == root,
                "Changed frozen pressure or root identity")
        key = (root, row["regime"], rho, scale, rep)
        require(key not in keys, "Duplicate paired deployment")
        keys.add(key)
        require(row["no_update"] in ("true", "false"), "Invalid no-update flag")
        adopted = row["no_update"] == "false"
        pg, gain, sf, uf = [float(row[k]) for k in
                           ("proxy_gain", "deployment_gain", "shortfall_gain_bps",
                            "unfilled_fraction_gain")]
        require(all(math.isfinite(v) for v in (pg, gain, sf, uf)), "Nonfinite input")
        require(row["failure_status"] == "ok", "Unresolved deployment in released cohort")
        require(adopted == (pg > TOL), "Adoption and proxy-positive status differ")
        require(adopted or (gain == sf == uf == 0
                            and row["candidate_id"] == row["incumbent_id"]),
                "No-update decision is not an exact incumbent zero")
        close(gain, sf + 100 * uf, "original 100 bps utility")
        identity = (row["candidate_id"], pg, adopted, row["config_hash"])
        skey = (root, row["regime"])
        require(skey not in selection or selection[skey] == identity,
                "Selection changed across deployment cells")
        selection[skey] = identity
        grouped.setdefault(key[:-1], []).append((gain, sf, uf))
    require(keys == expected and len(rows) == len(expected),
            "Missing, extra, or corrupt root/condition/replicate")
    cells = {k: tuple(sum(x[j] for x in values) / 4 for j in range(3))
             for k, values in grouped.items()}
    return cells, selection, rows


def original_contrasts(cells):
    names, values = [], []
    for g in REGIMES:
        for v in (0, 1):
            for s in SCALES:
                names.append(f"cell:{g}:rho{v}:{s}")
                values.append(cells[g, v, s])
    for g in REGIMES:
        for v in (0, 1):
            names.append(f"scale:{g}:rho{v}")
            values.append(cells[g, v, SCALES[-1]] - cells[g, v, SCALES[0]])
    for g in REGIMES:
        for s in SCALES:
            names.append(f"response:{g}:{s}")
            values.append(cells[g, 1, s] - cells[g, 0, s])
    for g in REGIMES:
        names.append(f"did:{g}")
        values.append(cells[g, 1, SCALES[-1]] - cells[g, 1, SCALES[0]]
                      - cells[g, 0, SCALES[-1]] + cells[g, 0, SCALES[0]])
    return names, values


def check_estimates(got, expected, label):
    require(set(got["estimates"]) == set(expected["estimates"]),
            f"Changed estimand family: {label}")
    close(got["joint_radius_bps"], expected["joint_radius_bps"], label + " radius")
    for name, row in expected["estimates"].items():
        for field in ("estimate_bps", "lower_bps", "upper_bps"):
            close(got["estimates"][name][field], row[field], f"{label}/{name}/{field}")


def market_report(directory, expected):
    cells, selections, rows = load_market(directory / "market_observations.csv")
    original, diagnostic = [], []
    for root in ROOTS:
        names, vector = original_contrasts(
            {(g, v, s): cells[root, g, v, s][0]
             for g in REGIMES for v in (0, 1) for s in SCALES})
        original.append(vector)
        dnames, dvector = [], []
        for penalty in PENALTIES:
            revalued = {(g, v, s): cells[root, g, v, s][1]
                        + penalty * cells[root, g, v, s][2]
                        for g in REGIMES for v in (0, 1) for s in SCALES}
            for g in REGIMES:
                for v in (0, 1):
                    for s in SCALES:
                        dnames.append(f"cell:p{penalty}:{g}:rho{v}:{s}")
                        dvector.append(revalued[g, v, s])
            for g in REGIMES:
                for v in (0, 1):
                    dnames.append(f"scale:p{penalty}:{g}:rho{v}")
                    dvector.append(revalued[g, v, SCALES[-1]] - revalued[g, v, SCALES[0]])
        diagnostic.append(dvector)
    orig = simultaneous_band(original, names, expected["market"]["bootstrap_seed_sha256"])
    diag = simultaneous_band(diagnostic, dnames, expected["penalty"]["bootstrap_seed_sha256"])
    check_estimates(orig, expected["market"], "original24")
    check_estimates(diag, expected["penalty"], "diagnostic64")
    summaries, prefixes = {}, {}
    for g in REGIMES:
        for v in (0, 1):
            for s in SCALES:
                key = f"{g}:rho{v}:{s}"
                summary = summarize_decisions([cells[r, g, v, s][0] for r in ROOTS],
                                              [selections[r, g][2] for r in ROOTS])
                old = expected["market"]["proxy_positive_reversal"][key]
                require((summary["reversals"], summary["selected_denominator"])
                        == (old["numerator"], old["denominator"]), "IRR count mismatch")
                summaries[key] = summary
            intervals = [(orig["estimates"][f"cell:{g}:rho{v}:{s}"]["lower_bps"],
                          orig["estimates"][f"cell:{g}:rho{v}:{s}"]["upper_bps"]) for s in SCALES]
            prefixes[f"{g}:rho{v}"] = positive_prefix(SCALES, intervals)
    return {
        "original24": orig, "diagnostic64": diag, "decision_summaries": summaries,
        "certified_positive_prefixes": prefixes,
        "utility_components": {f"{g}:rho{v}": {
            "shortfall_gain_bps": sum(cells[r, g, v, .3][1] for r in ROOTS) / len(ROOTS),
            "unfilled_difference_pp": 100 * sum(cells[r, g, v, .3][2] for r in ROOTS) / len(ROOTS)}
            for g in REGIMES for v in (0, 1)},
        "audit": {"paired_rows": len(rows), "root_clusters": 50, "selection_units": 100,
                  "no_update_selection_units": sum(not x[2] for x in selections.values()),
                  "missing_or_failed_rows": 0,
                  "scope": "saved outcomes; full event replay is not performed"},
    }


def proxy_deployment_gap_report(cells, selections, spec):
    """Outcome-aware paired gap between selected proxy scores and fresh deployment."""
    require(spec["schema"] == "proxy-deployment-gap-diagnostic-v1"
            and spec["identity"] == "proxy-deployment-gap-v1"
            and spec["evidence_class"] == "post-outcome diagnostic"
            and spec["outcome_aware"] is True, "Wrong proxy-gap diagnostic scope")
    require(spec["root_count"] == len(ROOTS) and spec["utility_preference_bps"] == 100
            and spec["deployment_replicates_per_root_cell"] == 4,
            "Changed proxy-gap cohort or utility")
    scale = float(spec["selection_scale"])
    require(scale == 0.05 and spec["family_size"] == 4,
            "Changed proxy-gap selection scale or family")
    names = [f"{g}:rho{v}" for g in REGIMES for v in (0, 1)]
    require(spec["cells"] == names, "Changed proxy-gap inferential family")

    gap_vectors, proxy_means, deployment_means = [], {name: [] for name in names}, {name: [] for name in names}
    for root in ROOTS:
        vector = []
        for g in REGIMES:
            candidate, proxy_gain, adopted, _ = selections[root, g]
            require(math.isfinite(proxy_gain), "Nonfinite selected proxy gain")
            procedure_proxy_gain = proxy_gain if adopted else 0.0
            for v in (0, 1):
                name = f"{g}:rho{v}"
                deployment_gain = cells[root, g, v, scale][0]
                proxy_means[name].append(procedure_proxy_gain)
                deployment_means[name].append(deployment_gain)
                vector.append(procedure_proxy_gain - deployment_gain)
        gap_vectors.append(vector)

    band = simultaneous_band(gap_vectors, names, spec["bootstrap_seed_sha256"],
                             draws=spec["bootstrap_draws"])
    return {
        "status": "completed-post-outcome-proxy-deployment-gap-diagnostic",
        "evidence_class": spec["evidence_class"],
        "outcome_aware": True,
        "selection_scale": scale,
        "utility_preference_bps": 100,
        "root_clusters": len(ROOTS),
        "deployment_replicates_per_root_cell": 4,
        "family_size": len(names),
        "inferential_family": band,
        "estimates": {
            name: {
                "proxy_mean_bps": sum(proxy_means[name]) / len(ROOTS),
                "deployment_mean_bps": sum(deployment_means[name]) / len(ROOTS),
                "gap": band["estimates"][name],
            }
            for name in names
        },
        "interpretation_limit": spec["interpretation_limit"],
        "new_selections": 0,
        "new_simulations": 0,
        "new_model_calls": 0,
    }


def check_proxy_gap_reference(got, expected):
    require(got["status"] == "completed-post-outcome-proxy-deployment-gap-diagnostic"
            and got["outcome_aware"] is True
            and expected["schema"] == "proxy-deployment-gap-reference-v1",
            "Wrong proxy-gap result status or reference")
    require(got["family_size"] == expected["family_size"] == 4
            and got["root_clusters"] == expected["root_clusters"] == 50
            and set(got["estimates"]) == set(expected["estimates"]),
            "Changed proxy-gap reference family")
    close(got["selection_scale"], expected["selection_scale"], "proxy-gap scale")
    require(got["inferential_family"]["bootstrap_draws"] == expected["bootstrap_draws"]
            and got["inferential_family"]["seed_sha256"] == expected["bootstrap_seed_sha256"],
            "Changed proxy-gap bootstrap specification")
    close(got["inferential_family"]["joint_radius_bps"],
          expected["joint_radius_bps"], "proxy-gap joint radius")
    for name, reference in expected["estimates"].items():
        row = got["estimates"][name]
        for field in ("proxy_mean_bps", "deployment_mean_bps"):
            close(row[field], reference[field], f"proxy-gap/{name}/{field}")
        for field in ("estimate_bps", "lower_bps", "upper_bps"):
            close(row["gap"][field], reference["gap"][field], f"proxy-gap/{name}/{field}")


def planner_report(directory, expected):
    data = read_json(directory / "planner_scores.json")
    cfg, proxy, deploy = data["config"], data["proxy"], data["deployment"]
    require(len(cfg["roots"]) == 3 and cfg["generation_attempts"] == 32,
            "Changed planner generation design")
    curves = {}
    for pressure in cfg["pressures"]:
        gains, proxies = [], []
        for root in cfg["roots"]:
            p = proxy["scores"][str(root)]
            d = deploy["scores"][str(root)]
            require(len(p) == 4 and len(d) == 20 and not set(p) & set(d),
                    "Changed proxy/deployment task split")
            require(all(len(v["attempt_values"]) == 32 for v in [*p.values(), *d.values()]),
                    "Missing planner attempts")
            pg = np.mean([np.asarray(v["attempt_values"]) - v["incumbent"]
                          for v in p.values()], axis=0)
            winner = max(range(pressure), key=lambda i: (pg[i], -i))
            winner = winner if pg[winner] > TOL else None
            require(winner == proxy["winners"][str(root)][str(pressure)],
                    "Saved planner selection differs")
            proxies.append(float(pg[winner]) if winner is not None else 0.0)
            gains.append([v["attempt_values"][winner] - v["incumbent"]
                          if winner is not None else 0.0 for v in d.values()])
        matrix = np.asarray(gains)
        require(np.isfinite(matrix).all(), "Nonfinite planner outcome")
        rng = np.random.default_rng(cfg["bootstrap_seed"])
        ri = rng.integers(0, 3, (cfg["bootstrap_replicates"], 3))
        ti = rng.integers(0, 20, (cfg["bootstrap_replicates"], 20))
        draws = matrix[ri[:, :, None], ti[:, None, :]].mean(axis=(1, 2))
        row = {"proxy_gain": float(np.mean(proxies)),
               "deployment_gain": float(matrix.mean()),
               "crossed_root_task_ci95": np.quantile(draws, [.025, .975]).tolist()}
        ref = expected["planner"][str(pressure)]
        for field in ("proxy_gain", "deployment_gain"):
            close(row[field], ref[field], f"planner/{pressure}/{field}")
        for a, b in zip(row["crossed_root_task_ci95"], ref["crossed_root_task_ci95"]):
            close(a, b, "planner pointwise interval")
        curves[str(pressure)] = row
    return {"curves": curves, "generation_roots": 3, "fixed_tasks": 20,
            "interval_scope": "exploratory crossed root/task bootstrap; pointwise"}


def write_paper_tables(report, directory):
    """The paper consumes these tables, generated from checked recomputation."""
    directory.mkdir(parents=True, exist_ok=True)
    endrow = r" \\"

    def emit(filename, columns, header, rows, caption, label, small=False, placement="t"):
        lines = [r"\begin{table}[" + placement + r"]\centering" + (r"\footnotesize" if small else r"\small"),
                 r"\begin{tabular}{" + columns + r"}\toprule", header + endrow,
                 r"\midrule", *[" & ".join(row) + endrow for row in rows],
                 r"\bottomrule\end{tabular}", r"\caption{" + caption + r"}\label{" + label + "}",
                 r"\end{table}"]
        (directory / filename).write_text("\n".join(lines) + "\n")

    def band(row, digits=2):
        return (f'${row["estimate_bps"]:.{digits}f}$',
                f'$[{row["lower_bps"]:.{digits}f},\\,{row["upper_bps"]:.{digits}f}]$')

    original = report["market"]["original24"]["estimates"]
    rows = []
    for g, name in zip(REGIMES, ("Liquid", "Thin")):
        for v in (0, 1):
            rows.append([name, f"${v}$", *band(original[f"cell:{g}:rho{v}:0.3"], 4)])
    emit("market_largest.tex", "llrr", r"Regime & $\rho$ & Mean & Simultaneous band", rows,
         r"Largest-scale procedure gains ($s=0.30$), in bps. The original 24-estimate family uses the prespecified 100 bps completion utility and all 50 shared roots.", "tab:largest")
    rows = []
    for key, row in original.items():
        parts = key.split(":")
        g = "Liquid" if parts[1] == REGIMES[0] else "Thin"
        if parts[0] == "cell":
            desc = f'Cell: $\\rho={parts[2][-1]}, s={parts[3]}$'
        elif parts[0] == "scale":
            desc = f'Scale: $\\rho={parts[2][-1]}$'
        elif parts[0] == "response":
            desc = f'Response: $s={parts[2]}$'
        else:
            desc = "Scale-by-response"
        rows.append([g, desc, *band(row, 4)])
    emit("all24.tex", "llrr", "Regime & Estimand & Mean & Simultaneous band", rows,
         r"All 24 prospective estimates in bps, using one shared-root maximum-deviation band. Scale denotes $0.30-0.002$; response denotes $1-0$. Unresolved contrasts are retained.", "tab:all24")
    diagnostic = report["market"]["diagnostic64"]["estimates"]
    rows = []
    for g, name in zip(REGIMES, ("Liquid", "Thin")):
        for v in (0, 1):
            row = [name, f"${v}$"]
            for p in PENALTIES:
                b = band(diagnostic[f"cell:p{p}:{g}:rho{v}:0.3"])
                row.append(r"\shortstack{" + b[0] + r"\\" + b[1] + "}")
            rows.append(row)
    emit("penalty_table.tex", "llrrrr", r"Regime & $\rho$ & $p=25$ & $p=50$ & $p=100$ & $p=200$", rows,
         r"Largest-scale fixed-selection revaluation (bps), with approximate simultaneous 95\% bands for the separate, outcome-aware 64-estimate family. Each entry is a mean and its band; no selection is rerun.", "tab:penalty", small=True)
    rows = []
    for g, name in zip(REGIMES, ("Liquid", "Thin")):
        for v in (0, 1):
            c = report["market"]["utility_components"][f"{g}:rho{v}"]
            rows.append([name, f"${v}$", f'{c["shortfall_gain_bps"]:+.3f}', f'{c["unfilled_difference_pp"]:+.3f}'])
    emit("components.tex", "llrr", r"Regime & $\rho$ & Shortfall gain (bps) & Unfinished difference (pp)", rows,
         r"Descriptive largest-scale utility components: incumbent minus selected shortfall and unfinished fraction. Multiply the final column by $p/100$ to obtain its utility contribution in bps. No additional inferential bands are assigned to these components.", "tab:components")
    gap = report["market"]["proxy_deployment_gap"]
    rows = []
    for name in gap["inferential_family"]["estimates"]:
        regime, response = name.split(":rho")
        row = gap["estimates"][name]
        band_row = row["gap"]
        label = "Liquid" if regime == "liquid_market" else "Thin"
        rows.append([label, f"${response}$", f'{row["proxy_mean_bps"]:.3f}',
                     f'{row["deployment_mean_bps"]:.3f}',
                     f'{band_row["estimate_bps"]:.3f}',
                     f'$[{band_row["lower_bps"]:.3f},\\,{band_row["upper_bps"]:.3f}]$'])
    emit("proxy_deployment_gap.tex", "llrrrr", r"Regime & $\rho$ & Proxy & Deploy. & $\widehat\Gamma$ & Joint band",
         rows, r"Outcome-aware comparison at the $s=0.05$ selection scale, in bps under the recorded $U_{100}$ convention. Proxy, deployment, and gap means use all 50 roots; the final column gives the approximate simultaneous 95\% whole-root bootstrap band for the four paired proxy-minus-deployment gaps. No-update roots contribute zero. This auxiliary family is separate from the original 24-estimate family.",
         "tab:proxy-deployment-gap", small=True, placement="H")
    rows = []
    for pressure, row in report["planner"]["curves"].items():
        lo, hi = row["crossed_root_task_ci95"]
        rows.append([pressure, f'{100*row["proxy_gain"]:.3f}', f'{100*row["deployment_gain"]:.3f}', f'$[{100*lo:.3f},\\,{100*hi:.3f}]$'])
    emit("planner_table.tex", "rrrr", "Attempts & Proxy gain & Deployment gain & Pointwise interval", rows,
         r"Planner-code gains in balanced-accuracy percentage points. Intervals use 10,000 exploratory crossed root/task bootstrap draws over three roots and the fixed 20-task panel; they are not simultaneous or independent-backbone evidence.", "tab:planner")


def set_scale_ticks(ax):
    ax.set_xticks(SCALES, labels=("0.002", "0.05", "0.30"))


def plot_reports(report, output):
    os.environ.setdefault("MPLCONFIGDIR", str(output / ".mplconfig"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    colors = ("#0072B2", "#D55E00")
    meta = {"Author": "", "CreationDate": None, "ModDate": None}
    estimates = report["market"]["original24"]["estimates"]
    fig, axes = plt.subplots(1, 2, figsize=(7, 2.8), sharey=True)
    for ax, g in zip(axes, REGIMES):
        for v, color in zip((0, 1), colors):
            y = [estimates[f"cell:{g}:rho{v}:{s}"]["estimate_bps"] for s in SCALES]
            ax.errorbar(SCALES, y, yerr=report["market"]["original24"]["joint_radius_bps"],
                        marker="o", capsize=3, color=color, label=rf"$\rho={v}$")
        ax.axhline(0, color=".4", lw=.8); ax.set_title(g.replace("_", " "))
        set_scale_ticks(ax)
        ax.set_xlabel("Deployment scale"); ax.legend()
    axes[0].set_ylabel("Procedure mean gain (bps)")
    fig.tight_layout(); fig.savefig(output / "market_scale.pdf", metadata=meta); plt.close(fig)
    fig, ax = plt.subplots(figsize=(6.2, 3.1))
    estimates = report["market"]["diagnostic64"]["estimates"]
    for g, color, offset in zip(REGIMES, colors, (-2, 2)):
        y = [estimates[f"cell:p{p}:{g}:rho0:0.3"]["estimate_bps"] for p in PENALTIES]
        ax.errorbar(np.asarray(PENALTIES) + offset, y,
                    yerr=report["market"]["diagnostic64"]["joint_radius_bps"],
                    marker="o", capsize=3, color=color, label=g.replace("_", " "))
        original = report["market"]["original24"]["estimates"][f"cell:{g}:rho0:0.3"]
        ax.errorbar([100 + offset], [original["estimate_bps"]],
                    yerr=report["market"]["original24"]["joint_radius_bps"],
                    fmt="D", markerfacecolor="white", color=color, capsize=6)
    ax.axhline(0, color=".4", lw=.8); ax.set_xticks(PENALTIES)
    ax.set_xlabel("Incomplete-fill penalty (bps)")
    ax.set_ylabel("Procedure mean gain (bps)")
    ax.set_title(r"Fixed selections; $s=0.30,\rho=0$; 64-estimate diagnostic")
    ax.legend(fontsize=8); fig.tight_layout()
    fig.savefig(output / "penalty_sensitivity.pdf", metadata=meta); plt.close(fig)
    curves = report["planner"]["curves"]
    x = [2, 4, 8, 16, 32]
    y = np.array([curves[str(p)]["deployment_gain"] for p in x]) * 100
    bounds = np.array([curves[str(p)]["crossed_root_task_ci95"] for p in x]) * 100
    fig, ax = plt.subplots(figsize=(5.5, 2.8))
    ax.errorbar(x, y, yerr=[y - bounds[:, 0], bounds[:, 1] - y], color=colors[0],
                marker="o", capsize=3, label="Deployment; pointwise 95% interval")
    ax.plot(x, [100 * curves[str(p)]["proxy_gain"] for p in x], "--o",
            color=colors[1], label="Proxy")
    ax.set_xscale("log", base=2); ax.set_xticks(x, labels=x)
    ax.set_xlabel("Search prefix (attempts)"); ax.set_ylabel("Balanced accuracy gain (pp)")
    ax.axhline(0, color=".4", lw=.8); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(output / "planner_prefix.pdf", metadata=meta); plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(__file__).resolve().parent / "data")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    require(not args.output.resolve().is_relative_to(args.data.resolve()),
            "Output must not overwrite packaged input data")
    provenance = verify_inputs(args.data)
    require(provenance["schema"] == "frozen-procedure-portable-evidence-v3", "Wrong release scope")
    expected = read_json(args.data / "expected.json")
    require(set(expected) == {"market", "penalty", "planner"}, "Unexpected evidence in scoped release")
    gap_spec = read_json(args.data / "proxy_deployment_gap_spec.json")
    gap_expected = read_json(args.data / "proxy_deployment_gap_expected.json")
    cells, selections, _ = load_market(args.data / "market_observations.csv")
    gap_report = proxy_deployment_gap_report(cells, selections, gap_spec)
    check_proxy_gap_reference(gap_report, gap_expected)
    report = {"status": "passed-saved-outcome-reanalysis",
              "market": {**market_report(args.data, expected),
                         "proxy_deployment_gap": gap_report},
              "planner": planner_report(args.data, expected),
              "verified_inputs": provenance["files"],
              "new_simulations": 0, "new_model_calls": 0, "new_task_fits": 0,
              "scientific_program_complete": False, "submission_ready": False}
    args.output.mkdir(parents=True, exist_ok=True)
    for family in ("original24", "diagnostic64"):
        with (args.output / (family + ".csv")).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["estimand", "estimate_bps", "lower_bps", "upper_bps"])
            writer.writeheader()
            for key, row in report["market"][family]["estimates"].items():
                writer.writerow({"estimand": key, **row})
    write_paper_tables(report, args.output / "generated")
    if not args.no_plots:
        plot_reports(report, args.output)
    write_json(args.output / "report.json", report)
    print(json.dumps({"status": report["status"], "paired_rows": 2400,
                      "root_clusters": 50, "original_family": 24, "diagnostic_family": 64,
                      "proxy_gap_family": gap_report["family_size"], "planner_prefixes": 5,
                      "new_model_calls": 0, "new_simulations": 0, "output": str(args.output)}))


if __name__ == "__main__":
    main()
