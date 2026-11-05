# Saved-outcome reanalysis: frozen procedure deployment utility (release 202611050855)

Use Python 3.10 (verified with 3.10.12), a separate virtual environment, and a
TeX installation providing latexmk, pdflatex, bibtex, and the packages in main.tex.

```bash
python3 -m venv /path/to/venv
/path/to/venv/bin/python -m pip install -r reproduction/requirements.txt
PATH=/path/to/venv/bin:$PATH bash reproduce_all.sh /path/to/output
```

Output must be separate from the input package. Run `sha256sum -c
SOURCE_SHA256SUMS` first to verify the complete package. After installing the
Python dependencies, the wrapper runs offline, without API keys or new episodes.

For numbers and plots without TeX, run:

```bash
python3 reproduction/reproduce.py --output /path/to/output
python3 reproduction/root_robustness.py --output /path/to/output/root-robustness --expected reproduction/data/root_robustness_expected.json
python3 reproduction/break_even.py --output /path/to/output/break-even --expected reproduction/data/break_even_expected.json
```

The full wrapper also assembles fresh tables/figures into output/paper-source
and compiles output/paper/main.pdf and supplement.pdf. Packaged generated files
are convenient snapshots; they are never substituted for recomputed outputs.
`build-inputs.json` identifies exactly what the compiler used.

## Inputs and units

`market_observations.csv` has 2,400 rows with unique
(root_id, regime, response_value, deployment_scale, replicate) keys. Fifty roots
are shared across both regimes. Four paired repetitions are averaged within root.
Selection uses 16 candidates and the original 100 bps completion utility.

| Field | Meaning |
|---|---|
| root_id, seed | Independent root identity (8101–8150); not a count of independent episodes |
| regime | liquid_market or thin_market |
| candidate_id, incumbent_id | Frozen adopted choice, or identical IDs for no update |
| proxy_gain | Saved selected mean proxy improvement in bps |
| deployment_gain | Paired deployment improvement at 100 bps |
| search_pressure | 16, fixed for the entire principal cohort |
| deployment_scale | 0.002, 0.05, 0.30 of calibrated background volume |
| response_type, response_value | Provider inventory-price response, off/on (0/1) |
| replicate | One of four deployment repetitions per cell |
| no_update | True only when the original rule retained the incumbent |
| config_hash | Hash identifying the original frozen selection protocol |
| failure_status | Must be ok for this complete cohort; failed rows are not imputed |
| shortfall_gain_bps | Incumbent minus selected implementation shortfall |
| unfilled_fraction_gain | Incumbent minus selected unfinished fraction |

Utility revaluation is shortfall_gain_bps + p * unfilled_fraction_gain. It holds
selection fixed at its original 100 bps choices. No-update component values
must all be zero. Missing, duplicate, nonfinite, or inconsistent data fail checks.

`planner_scores.json` retains the original proxy/deployment score arrays,
ordered attempt positions, saved winners and bootstrap configuration. It has
three generation roots, four proxy tasks, twenty deployment tasks, and 32
attempts per root. Invalid/duplicate attempts retain their positions as in the
original scored input; this reduced file does not include raw generation text.

`expected.json` binds the original 24 market estimates, the separate 64-estimate
utility diagnostic, and five planner summaries. `root_robustness_spec.json` and
`root_robustness_expected.json` bind the existing post-outcome diagnostics.
`provenance.json` records SHA-256 input inventories and original source bindings.

`proxy_deployment_gap_spec.json` and `proxy_deployment_gap_expected.json` bind a
separate outcome-aware comparison at the $s=0.05$ candidate-selection scale.
It compares the recorded selected-candidate proxy gain (zero for no-update)
with the average of four paired interactive deployment gains under $U_{100}$.
Four root-paired differences receive a 20,000-draw whole-root max-deviation
band. This diagnostic is outside the original 24-estimate family and does not
identify causal proxy bias.

## Interpretation

All 24 original means/contrasts share the 50-root resampling and 20,000-draw
max-deviation band. The 64-estimate family is an outcome-aware fixed-selection
revaluation. Root deletion and four alternative constructions are diagnostics,
not new confirmations; no coverage is asserted jointly across their methods.
Descriptive adopted-root sign counts are based on noisy four-repeat root means,
not noise-corrected reversal probabilities. Planner intervals are exploratory
and pointwise, with only three generation roots and a fixed task panel.

The scripts check numerical equality within 1e-9 in native units. The release
contains no game or PIVOT-KG evaluation. Related manuscript PDF material is for
comparison only. There are no raw model generations, full exchange event streams,
original task fits, or claim of a new independent scientific replication.

## Break-even completion utility (v6 addition)

`break_even_spec.json` identifies a new **outcome-aware** diagnostic specified
after inspection of v5 results and component means. `break_even_expected.json`
binds its reference computation. The original 24 and diagnostic 64 families
are unchanged. At the largest scale, each root contributes eight means: two
utility components in four regime/response conditions. No-update zeros remain.

The mean utility is a + p*b. Its zero, when b is nonzero, is -a/b, the ratio of
mean components, not the average of root-specific ratios. Unfinished fraction
is a proportion; multiply by 100 to display percentage points. The penalty p
is in bps. The raw null-shortfall convention is inherited from the original
utility, and the diagnostic does not reinterpret it or reselect policies.

20,000 shared-root PCG64 draws (seed 20261104) produce an approximate simultaneous
95% rectangle across all eight components using a fixed-sample-SE maximum.
Projecting the rectangle onto a+p*b=0 for p >= 0 gives a bounded, unbounded,
or empty set as appropriate. A nonempty set does not prove that a nonnegative
population zero exists. No coverage is asserted jointly with other analyses.
The nominal level treats this diagnostic as fixed; it does not adjust for the
choice of analysis after inspecting outcomes.

`break-even/break_even.json` includes all component intervals, zero sets, and
denominator-instability counts; `root_components.csv` retains all 50 roots.
Simple percentile ratios are reported only if every resampled denominator has
the observed sign. Both liquid conditions have three sign changes, so their
percentile summaries are omitted; all draws remain in the component bootstrap.
The two thin-cell percentile summaries are pointwise, not the joint sets used
in the paper. Constant empirical components are rejected by this standardized
diagnostic, since zero observed variation is not known population certainty.
