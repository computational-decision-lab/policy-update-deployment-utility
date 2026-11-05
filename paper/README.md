# Evaluating the Deployment Utility of a Frozen Policy-Update Procedure — release 202611050855

The `main.pdf` submission manuscript and `supplement.pdf` are separate. This
release contains the code and saved-outcome inputs needed to reproduce the
reported tables, figures, and diagnostics. A merged reading bundle is not the
submission manuscript.

See `reproduction/README.md` for dependencies, data dictionary, inferential
units, and the exact saved-outcome workflow. The main and supplementary PDFs
are built from recomputed tables and figures with:

```bash
bash reproduce_all.sh /path/to/output
```

This package includes the principal matching-engine outcomes, declared
diagnostics, the proxy-to-deployment comparison at the selection scale, and
the bounded planner-code case in the supplement. The proxy comparison is an
outcome-aware auxiliary analysis, separate from the original 24-estimate
family. The package uses inherited evaluation concepts with attribution. It
is not a new selection algorithm or a scientific rerun from raw model
generations, original tasks, or full exchange events.
