#!/usr/bin/env python3
"""Render a research-blog Markdown file as a paginated, classic LaTeX PDF.

Supported Markdown: headings, paragraphs, unordered/ordered lists, blockquotes,
horizontal rules, links, inline code, emphasis, strong emphasis, and inline math.
The source Markdown remains the single source of article text.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def tex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in value)


def inline_tex(text: str) -> str:
    """Convert inline Markdown while protecting math and generated TeX."""
    tokens: list[str] = []

    def token(value: str) -> str:
        marker = f"@@BLOGTOKEN{len(tokens)}@@"
        tokens.append(value)
        return marker

    for source, target in (
        ("4.62×10⁻¹³", r"$4.62\times 10^{-13}$"),
        ("10⁻⁷", r"$10^{-7}$"),
        ("10⁻¹¹", r"$10^{-11}$"),
        ("x²", r"$x^2$"),
        ("∈", r"$\in$"),
        ("≤", r"$\leq$"),
        ("ρ", r"$\rho$"),
        ("λ", r"$\lambda$"),
        ("×", r"$\times$"),
        ("≈", r"$\approx$"),
        ("→", r"$\rightarrow$"),
    ):
        text = text.replace(source, token(target))

    # Math is already valid LaTeX in the source article.
    text = re.sub(r"\$([^$]+)\$", lambda m: token("$" + m.group(1) + "$"), text)
    def render_code(match: re.Match[str]) -> str:
        value = match.group(1)
        escaped = tex_escape(value)
        if len(value) > 8:
            escaped = r"\allowbreak{}".join(
                tex_escape(value[index : index + 6]) for index in range(0, len(value), 6)
            )
        return token(r"\texttt{" + escaped + "}")

    text = re.sub(r"`([^`]+)`", render_code, text)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: token(
            r"\href{" + tex_escape(m.group(2)) + "}{" + tex_escape(m.group(1)) + "}"
        ),
        text,
    )
    text = re.sub(
        r"\*\*([^*]+)\*\*",
        lambda m: token(r"\textbf{" + tex_escape(m.group(1)) + "}"),
        text,
    )
    text = re.sub(
        r"(?<!\*)\*([^*]+)\*(?!\*)",
        lambda m: token(r"\emph{" + tex_escape(m.group(1)) + "}"),
        text,
    )
    escaped = tex_escape(text)
    for index, value in reversed(list(enumerate(tokens))):
        escaped = escaped.replace(f"@@BLOGTOKEN{index}@@", value)
    return escaped


def render_body(markdown: str) -> tuple[str, str]:
    lines = markdown.replace("\r\n", "\n").splitlines()
    title = "Research Blog"
    blocks: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    list_items: list[str] = []
    title_seen = False
    table_lines: list[str] = []
    code_lines: list[str] | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            blocks.append(inline_tex(" ".join(part.strip() for part in paragraph)))
            paragraph = []

    def flush_list() -> None:
        nonlocal list_kind, list_items
        if list_kind and list_items:
            blocks.append(r"\begin{" + list_kind + "}\n" + "\n".join(list_items) + r"\end{" + list_kind + "}")
        list_kind = None
        list_items = []

    def flush_table() -> None:
        nonlocal table_lines
        if not table_lines:
            return
        rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in table_lines
                if not re.fullmatch(r"[|\s:\-]+", line)]
        n = len(rows[0])
        if any(len(row) != n for row in rows):
            raise ValueError("Uneven Markdown table")
        widths = {2: [.22, .78], 3: [.20, .36, .44], 4: [.17, .27, .28, .28]}.get(n, [1/n]*n)
        columns = "".join(r">{\raggedright\arraybackslash}p{\dimexpr" + f"{w:.3f}" +
                          r"\linewidth-2\tabcolsep\relax}" for w in widths)
        header = " & ".join(r"\textbf{" + inline_tex(c) + "}" for c in rows[0]) + r" \\"
        content = [r"\begingroup\small\renewcommand{\arraystretch}{1.22}",
                   r"\begin{longtable}{" + columns + "}", r"\toprule", header,
                   r"\midrule\endfirsthead", r"\toprule", header, r"\midrule\endhead"]
        content += [" & ".join(inline_tex(c) for c in row) + r" \\" for row in rows[1:]]
        content += [r"\bottomrule\end{longtable}\endgroup"]
        blocks.append("\n".join(content))
        table_lines = []

    for raw in lines:
        line = raw.strip()
        if code_lines is not None:
            if line.startswith("```"):
                blocks.append(r"\begin{lstlisting}" + "\n" + "\n".join(code_lines) + "\n" + r"\end{lstlisting}")
                code_lines = None
            else:
                code_lines.append(raw)
            continue
        if line.startswith("```"):
            flush_paragraph()
            flush_list()
            flush_table()
            code_lines = []
            continue
        if line.startswith("|") and line.endswith("|"):
            flush_paragraph()
            flush_list()
            table_lines.append(line)
            continue
        flush_table()
        if not line:
            flush_paragraph()
            flush_list()
            continue
        if line == "---":
            flush_paragraph()
            flush_list()
            blocks.append(r"\medskip")
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            level, text = len(heading.group(1)), heading.group(2).strip()
            if level == 1 and not title_seen:
                title = text
                title_seen = True
                continue
            command = "section" if level == 2 else "subsection"
            blocks.append("\\" + command + "*{" + inline_tex(text) + "}")
            continue
        bullet = re.match(r"^[-+*]\s+(.+)$", line)
        numbered = re.match(r"^\d+[.)]\s+(.+)$", line)
        if bullet or numbered:
            flush_paragraph()
            wanted = "itemize" if bullet else "enumerate"
            if list_kind != wanted:
                flush_list()
                list_kind = wanted
            list_items.append(r"\item " + inline_tex((bullet or numbered).group(1)))
            continue
        if line.startswith("> "):
            flush_paragraph()
            flush_list()
            blocks.append(r"\begin{quote}" + inline_tex(line[2:]) + r"\end{quote}")
            continue
        if line.startswith("#"):
            flush_paragraph()
            flush_list()
            blocks.append(inline_tex(line))
            continue
        flush_list()
        paragraph.append(line)

    flush_paragraph()
    flush_list()
    flush_table()
    if code_lines is not None:
        raise ValueError("Unclosed Markdown code fence")
    return title, "\n\n".join(blocks)


def build_document(markdown: str, running_label: str, document_type: str = "Research Blog") -> str:
    title, body = render_body(markdown)
    safe_label = tex_escape(running_label)
    safe_type = tex_escape(document_type)
    return rf"""\documentclass[11pt,a4paper]{{article}}
\usepackage{{fontspec}}
\setmainfont{{Latin Modern Roman}}
\setsansfont{{Latin Modern Sans}}
\setmonofont{{Latin Modern Mono}}
\usepackage[margin=27mm,top=24mm,bottom=25mm,headheight=24pt]{{geometry}}
\usepackage{{microtype}}
\usepackage{{xcolor}}
\definecolor{{deepblue}}{{HTML}}{{1D409E}}
\usepackage{{fancyhdr}}
\usepackage{{lastpage}}
\usepackage{{parskip}}
\usepackage{{longtable,array,booktabs,listings}}
\lstset{{basicstyle=\ttfamily\scriptsize,breaklines=true,columns=fullflexible,keepspaces=true,showstringspaces=false}}
\setlength{{\parskip}}{{0.62em}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\emergencystretch}}{{2em}}
\usepackage{{hyperref}}
\hypersetup{{colorlinks=true,linkcolor=deepblue,urlcolor=deepblue,pdftitle={{{tex_escape(title)}}},pdfsubject={{{safe_type}}}}}
\pagestyle{{fancy}}
\fancyhf{{}}
\fancyhead[L]{{\textcolor{{deepblue}}{{\scriptsize {safe_label}}}}}
\fancyhead[R]{{\textcolor{{deepblue}}{{\scriptsize {safe_type}}}}}
\fancyfoot[C]{{\small\thepage\ / \pageref{{LastPage}}}}
\renewcommand{{\headrulewidth}}{{0pt}}
\begin{{document}}
\begin{{center}}
{{\LARGE\bfseries {inline_tex(title)}}}\\[0.8em]
{{\small\textsc{{{safe_type}}}}}
\end{{center}}
\vspace{{0.7em}}
{body}
\end{{document}}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="source Markdown article")
    parser.add_argument("output", type=Path, nargs="?", help="output PDF path (defaults beside input)")
    args = parser.parse_args()

    source = args.input.resolve()
    output = (args.output or source.with_suffix(".pdf")).resolve()
    if not source.is_file():
        parser.error(f"input does not exist: {source}")
    if shutil.which("xelatex") is None:
        parser.error("xelatex is required; install a XeLaTeX distribution with Latin Modern fonts")

    markdown = source.read_text(encoding="utf-8")
    if "DEPLOYMENT" in source.name.upper():
        label = "Research note"
    elif "CAAW" in source.name.upper():
        label = "CAAW 2027"
    else:
        label = "ICBC 2027"
    kind = "Research Blog"
    if "FORENSIC" in source.name.upper():
        label, kind = "CAAW and ICBC 2027", "Validation Report"
    tex = build_document(markdown, label, kind)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="research_blog_pdf_") as temp_dir:
        work = Path(temp_dir)
        tex_path = work / output.with_suffix(".tex").name
        tex_path.write_text(tex, encoding="utf-8")
        for _ in range(2):
            subprocess.run(
                ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
                cwd=work,
                check=True,
                stdout=subprocess.DEVNULL,
            )
        log_text = tex_path.with_suffix(".log").read_text(encoding="utf-8", errors="replace")
        warnings = [
            line.strip()
            for line in log_text.splitlines()
            if re.search(r"(?:LaTeX|Package .*?) Warning:|Overfull \\hbox|Underfull \\hbox", line)
        ]
        if warnings:
            print("LaTeX warnings:", file=sys.stderr)
            for warning in warnings:
                print(warning, file=sys.stderr)
        else:
            print("latex_warnings=0")
        shutil.copy2(tex_path.with_suffix(".pdf"), output)
    print(output)


if __name__ == "__main__":
    main()
