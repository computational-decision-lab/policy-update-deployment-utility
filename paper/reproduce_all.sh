#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 1 ]; then
  printf 'Usage: bash reproduce_all.sh OUTPUT_DIRECTORY\n' >&2
  exit 2
fi
package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
output_dir="$(realpath -m -- "$1")"
python3 - "$package_dir" "$output_dir" <<'PY'
from pathlib import Path
import sys
p, o = map(lambda x: Path(x).resolve(), sys.argv[1:])
if o == p or o.is_relative_to(p) or p.is_relative_to(o):
    raise SystemExit('Output must be separate from the source package')
PY
mkdir -p "$output_dir"
export PYTHONDONTWRITEBYTECODE=1
export MPLCONFIGDIR="$output_dir/.mplconfig"
python3 "$package_dir/reproduction/reproduce.py" --output "$output_dir"
python3 "$package_dir/reproduction/root_robustness.py" \
  --output "$output_dir/root-robustness" \
  --expected "$package_dir/reproduction/data/root_robustness_expected.json"
python3 "$package_dir/reproduction/break_even.py" \
  --output "$output_dir/break-even" \
  --expected "$package_dir/reproduction/data/break_even_expected.json"
python3 "$package_dir/reproduction/prepare_build.py" --package "$package_dir" --output "$output_dir"
mkdir -p "$output_dir/paper"
cd "$output_dir/paper-source"
export TEXINPUTS="./style:"
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir="$output_dir/paper" main.tex
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir="$output_dir/paper" supplement.tex
