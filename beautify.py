#!/usr/bin/env python3
"""Format Pulpit's first-party JavaScript and CSS with jsbeautifier / cssbeautifier.

The beautifiers are the JS/CSS counterpart of `ruff format` for Python: they own
whitespace, indentation and brace placement so nobody has to review it. The
options below are the project's house style and the only place they are defined —
always run through this script rather than calling `js-beautify` / `css-beautify`
by hand, or the next run will churn the file back.

    python beautify.py                 # every tracked .js / .css file
    python beautify.py path [path …]   # only these files / directories
    python beautify.py --check         # report what would change, write nothing

Install the formatters with `pip install -r requirements_dev.txt`.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import cssbeautifier
import jsbeautifier

ROOT = Path(__file__).resolve().parent

# ── House style ───────────────────────────────────────────────────────────────
# JS: 4-space indent (as written across the codebase). `preserve-inline` keeps
# short object literals and import destructurings on one line — the dominant
# idiom here — instead of exploding every `{ a: 1, b: 2 }` over three lines.
JS_OPTIONS = {
    "indent_size": 4,
    "brace_style": "collapse,preserve-inline",
    "end_with_newline": True,
}
# CSS: 2-space indent, the convention of every stylesheet but graph.css.
CSS_OPTIONS = {
    "indent_size": 2,
    "end_with_newline": True,
}
MAX_PASSES = 5


def _options(defaults, overrides):
    opts = defaults()
    for key, value in overrides.items():
        setattr(opts, key, value)
    return opts


def _tracked_files() -> list[Path]:
    """Every .js / .css file git knows about — vendored and generated trees are excluded by construction."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.js", "*.css"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(ROOT / name for name in out.split("\0") if name)


def _expand(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(p for p in sorted(path.rglob("*")) if p.suffix in (".js", ".css"))
        elif path.suffix in (".js", ".css"):
            files.append(path)
        else:
            sys.exit(f"Not a JavaScript or CSS file: {path}")
    return files


def beautify(path: Path) -> str:
    """Return the formatted text of a .js / .css file.

    A single jsbeautifier pass is not always a fixed point — a block written
    inline (`if (x) { a; b; }`) comes out half-expanded and only settles on the
    next pass — so beautify until the text stops moving. Every file in this
    repository converges on the second pass; the cap is a runaway guard.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".js":
        run, opts = jsbeautifier.beautify, _options(jsbeautifier.default_options, JS_OPTIONS)
    else:
        run, opts = cssbeautifier.beautify, _options(cssbeautifier.default_options, CSS_OPTIONS)
    for _ in range(MAX_PASSES):
        formatted = run(text, opts)
        if formatted == text:
            return text
        text = formatted
    sys.exit(f"{path}: formatting did not settle after {MAX_PASSES} passes")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", help="Files or directories to format (default: all tracked JS/CSS)")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if any file would change; write nothing")
    args = parser.parse_args()

    files = _expand(args.paths) if args.paths else _tracked_files()
    changed = []
    for path in files:
        formatted = beautify(path)
        if formatted != path.read_text(encoding="utf-8"):
            changed.append(path)
            if not args.check:
                path.write_text(formatted, encoding="utf-8")

    verb = "would be reformatted" if args.check else "reformatted"
    for path in changed:
        print(f"{verb}: {path.relative_to(ROOT) if path.is_absolute() else path}")
    print(f"{len(changed)} file{'s' if len(changed) != 1 else ''} {verb}, {len(files) - len(changed)} already clean")
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())
