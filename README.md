# Deployment Utility Evaluation

Release `202611050855` accompanies the paper *Evaluating the Deployment Utility of a Frozen Policy-Update Procedure: Scale, Completion Preference, and Joint Evidence*.

Repository: <https://github.com/computational-decision-lab/policy-update-deployment-utility>

This repository contains the portable saved-outcome reanalysis package. It includes the manuscript and supplement source, the research slides source, the technical reading note, the saved market outcomes, and the scripts that rebuild all reported tables, figures, and diagnostics. The package does not contain raw generation transcripts, full exchange event streams, or private comparison materials.

The main paper is an applied policy-evaluation study. Its primary statistical unit is the independent generation root (`n = 50`); the `2,400` paired deployment rows are repeated observations within that clustered design. The release performs no new model calls, candidate selections, or market simulations.

## Reproduce

Use Python 3.10 and a TeX installation providing `latexmk`, `pdflatex`, `bibtex`, and the packages used by the TMLR style.

```bash
cd paper
python3 -m venv /tmp/deployment-utility-venv
/tmp/deployment-utility-venv/bin/python -m pip install -r reproduction/requirements.txt
PATH=/tmp/deployment-utility-venv/bin:$PATH bash reproduce_all.sh /tmp/deployment-utility-output
```

The output directory must be separate from `paper/`. The wrapper checks the saved outcomes, recomputes the numerical results, rebuilds the LaTeX inputs, and writes the manuscript and supplement PDFs. No network access or secret key is required after dependencies are installed.

## Contents

- [`paper/main.tex`](paper/main.tex): manuscript source.
- [`paper/supplement.tex`](paper/supplement.tex): supplementary material source.
- [`paper/reproduction/`](paper/reproduction/): saved-outcome analysis scripts and data.
- [`paper/slides/tmlr_deployment_utility_slides.tex`](paper/slides/tmlr_deployment_utility_slides.tex): research slides source.
- [`paper/blog/deployment_utility_technical_blog.md`](paper/blog/deployment_utility_technical_blog.md): technical reading note source.
- [`release/tmlr-deployment-utility-202611050855-complete.pdf`](release/tmlr-deployment-utility-202611050855-complete.pdf): dated 47-page reading bundle containing the manuscript, supplement, slides, and blog.
- [`release/policy-update-deployment-utility-202611050855-reproducibility.zip`](release/policy-update-deployment-utility-202611050855-reproducibility.zip): dated source-and-data archive for offline reproduction.

The manuscript's first-page footnote points to this repository and the same dated release identifier.

## Data scope

The included `market_observations.csv` contains 2,400 paired rows from 50 shared roots, two liquidity regimes, three order scales, two response settings, and four deployment repetitions. The accompanying JSON specifications bind the original 24-estimate family and separately scoped post-outcome diagnostics. The data are saved outcomes for transparent reanalysis, not a complete regeneration of the underlying candidate-generation or market-event process.

## Integrity

Run `sha256sum -c paper/SOURCE_SHA256SUMS` before analysis. The release manifest and checksums for the complete reading bundle are in [`release/`](release/).
