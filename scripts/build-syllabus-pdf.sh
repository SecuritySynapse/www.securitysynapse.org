#!/usr/bin/env bash
#
# build-syllabus-pdf.sh - build one self-contained "syllabus PDF" for the course.
#
# The script renders the two Quarto pages that describe the course structure and
# joins them into a single PDF, syllabus first and schedule second:
#
#   syllabus/index.qmd   ->  part 1  (its own title page, contents, numbering)
#   schedule/index.qmd   ->  part 2  (its own title page, contents, numbering)
#
# The joined file preserves:
#   * the complete nested bookmark (outline) tree of both parts
#   * every internal cross-reference, so both "Contents" pages navigate
#   * every external hyperlink
#   * PDF document metadata (title, author, subject)
#
# The two .qmd files are never modified and the website build is not touched;
# all intermediate files live in a temporary directory that is removed on exit.
#
# Usage:
#   scripts/build-syllabus-pdf.sh [options]
#
# Options:
#   -o, --output PATH   write the joined PDF to PATH
#                       (default: export/syllabus-and-schedule.pdf)
#   -k, --keep          keep the intermediate PDFs and write their location
#   -v, --verbose       show the full Quarto render output for each part
#       --open          open the finished PDF with the desktop viewer
#   -h, --help          show this help
#
# Requirements (NixOS package names in parentheses):
#   quarto      (quarto)
#   LuaLaTeX    (texlive.combined.scheme-full, or scheme-medium plus texlive.enumitem)
#   uv          (uv) - used to run the PDF merge step with pypdf
#
# If a tool is missing, add it to environment.systemPackages, or run this script
# from an ad-hoc shell that provides all three:
#
#   nix-shell -p quarto texlive.combined.scheme-full uv --run scripts/build-syllabus-pdf.sh

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Parts of the joined PDF, in the order in which they must appear.
PARTS=(syllabus schedule)

# Default output location, relative to the project root. "export/" is ignored
# by git, so the generated artifact never shows up as an untracked file.
DEFAULT_OUTPUT="export/syllabus-and-schedule.pdf"

# The Quarto output format to render each part with.
PDF_FORMAT="pdf"

# The pypdf requirement used for the merge step.
PYPDF_REQUIREMENT="pypdf>=6,<7"

# Document metadata written into the joined PDF (overridable via environment).
PDF_TITLE="${PDF_TITLE:-Computer Science 203: Syllabus and Schedule}"
PDF_AUTHOR="${PDF_AUTHOR:-Gregory M. Kapfhammer}"
PDF_SUBJECT="${PDF_SUBJECT:-Course syllabus and course schedule}"

# ---------------------------------------------------------------------------
# Output helpers (Nerd Font icons, no emoji)
# ---------------------------------------------------------------------------

# Nerd Font glyphs from the Material Design Icons set. bash's \u escape takes
# exactly four hex digits, so the supplementary-plane codepoints need \U with
# eight digits: $'\uf012c' would decode to U+F012 followed by a literal "c".
readonly ICON_OK=$'\U000f012c'    # md-check_circle
readonly ICON_BAD=$'\U000f0156'   # md-close_circle
readonly ICON_WARN=$'\U000f0026'  # md-alert
readonly ICON_FILE=$'\U000f0219'  # md-file_document
readonly ICON_GEAR=$'\U000f0493'  # md-cog
readonly ICON_ARROW=$'\U000f0054' # md-arrow_right

info() { printf ' %s  %s\n' "$ICON_GEAR" "$*" >&2; }
step() { printf ' %s  %s\n' "$ICON_ARROW" "$*" >&2; }
ok() { printf ' %s  %s\n' "$ICON_OK" "$*" >&2; }
warn() { printf ' %s  %s\n' "$ICON_WARN" "$*" >&2; }
die() {
  printf ' %s  %s\n' "$ICON_BAD" "$*" >&2
  exit 1
}

usage() {
  # Print the leading comment block of this script, minus the shebang line.
  awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"
  exit 0
}

# ---------------------------------------------------------------------------
# Project paths and argument parsing
# ---------------------------------------------------------------------------

SCRIPT_DIR="$PWD"

# Follow symlinks so that a symlinked copy on PATH still finds the project.
resolve_self() {
  local self="${BASH_SOURCE[0]}" target dir
  local -i hops=0

  while [[ -L $self ]] && ((hops++ < 40)); do
    target="$(readlink -- "$self" 2>/dev/null)" || break
    [[ -n $target ]] || break
    if [[ $target == /* ]]; then
      self="$target"
    else
      dir="${self%/*}"
      [[ $dir == "$self" ]] && dir="."
      self="$dir/$target"
    fi
  done

  printf '%s' "$self"
}

SCRIPT_PATH="$(resolve_self)"
SCRIPT_DIR="$(cd -- "${SCRIPT_PATH%/*}" 2>/dev/null && pwd)" || SCRIPT_DIR="$PWD"

# Resolve the project root without external tools: the script must be able to
# report missing dependencies even when PATH provides almost nothing.
#
# The script is normally at <project>/scripts/build-syllabus-pdf.sh, but it also
# has to work when it is invoked through a symlink, from a copy somewhere inside
# the project, or with a different current directory. So walk up from the
# script's own directory looking for the Quarto project file, and fall back to
# the invocation directory.
find_project_root() {
  local dir="$SCRIPT_DIR" candidate

  while [[ -n $dir ]]; do
    if [[ -f "$dir/_quarto.yml" ]]; then
      printf '%s' "$dir"
      return 0
    fi
    [[ $dir == "/" ]] && break
    candidate="${dir%/*}"
    dir="${candidate:-/}"
  done

  if [[ -f "$PWD/_quarto.yml" ]]; then
    printf '%s' "$PWD"
    return 0
  fi

  return 1
}

PROJECT_ROOT="$(find_project_root)" || {
  printf ' %s  Cannot find the Quarto project root (_quarto.yml).\n' "$ICON_BAD" >&2
  printf '    Run this script from the repository, or use the copy inside it:\n' >&2
  printf '      ./scripts/build-syllabus-pdf.sh\n' >&2
  exit 1
}

OUTPUT="$PROJECT_ROOT/$DEFAULT_OUTPUT"
KEEP_INTERMEDIATES=false
VERBOSE=false
OPEN_AFTER=false

# Temporary working directory. Global because the EXIT trap outlives main().
BUILD_DIR=""

while (($# > 0)); do
  case "$1" in
    -o | --output)
      (($# >= 2)) || die "--output needs a path argument"
      OUTPUT="$2"
      shift 2
      ;;
    -o=* | --output=*)
      OUTPUT="${1#*=}"
      shift
      ;;
    -k | --keep)
      KEEP_INTERMEDIATES=true
      shift
      ;;
    -v | --verbose)
      VERBOSE=true
      shift
      ;;
    --open)
      OPEN_AFTER=true
      shift
      ;;
    -h | --help)
      usage
      ;;
    *)
      die "unknown argument: $1 (try --help)"
      ;;
  esac
done

# A relative --output is interpreted relative to the project root.
[[ $OUTPUT = /* ]] || OUTPUT="$PROJECT_ROOT/$OUTPUT"

# ---------------------------------------------------------------------------
# Preflight: required tools
# ---------------------------------------------------------------------------

preflight() {
  local missing=()
  command -v quarto >/dev/null 2>&1 || missing+=("quarto (NixOS: quarto)")
  command -v uv >/dev/null 2>&1 || missing+=("uv (NixOS: uv)")

  if ! command -v lualatex >/dev/null 2>&1 &&
    ! command -v xelatex >/dev/null 2>&1 &&
    ! command -v tectonic >/dev/null 2>&1; then
    missing+=("a LaTeX engine, e.g. lualatex (NixOS: texlive.combined.scheme-full)")
  fi

  if ((${#missing[@]} > 0)); then
    {
      printf ' %s  Missing required tools:\n' "$ICON_BAD"
      printf '      - %s\n' "${missing[@]}"
      printf '\n'
      printf '    Add them to environment.systemPackages, or run this script in an\n'
      printf '    ad-hoc shell that provides everything:\n\n'
      printf '      nix-shell -p quarto texlive.combined.scheme-full uv --run %s\n' \
        "scripts/${BASH_SOURCE[0]##*/}"
    } >&2
    exit 1
  fi

  for part in "${PARTS[@]}"; do
    [[ -f "$PROJECT_ROOT/$part/index.qmd" ]] ||
      die "missing source file: $part/index.qmd"
  done
}

# ---------------------------------------------------------------------------
# LaTeX header fragments
# ---------------------------------------------------------------------------

# Two rendering problems have to be fixed before LaTeX can produce usable PDFs.
#
# 1. Deeply nested lists. The syllabus nests bullet lists five levels deep and
#    the schedule six; LaTeX's itemize environment stops at four and aborts the
#    build with "LaTeX Error: Too deeply nested". enumitem removes that limit.
#
# 2. Destination-name collisions. hyperref names every anchor from counters that
#    both documents start at 1, so both PDFs contain destinations called
#    "subsection*.1", "page.1", "Doc-Start", and so on. Merging such PDFs leaves
#    one name per collision, which sends half of the links to the wrong page.
#    \HyperDestNameFilter prefixes every destination with the part name, so the
#    two parts cannot collide and the merge stays exact.
write_headers() {
  local build_dir="$1" part

  for part in "${PARTS[@]}"; do
    cat >"$build_dir/header-$part.tex" <<'LATEX'
% ---- Allow lists nested deeper than LaTeX's default limit of four ----------
\usepackage{enumitem}
\setlistdepth{9}
\renewlist{itemize}{itemize}{9}
\renewlist{enumerate}{enumerate}{9}
\setlist[itemize,1]{label=\textbullet}
\setlist[itemize,2]{label=\textendash}
\setlist[itemize,3]{label=\textasteriskcentered}
\setlist[itemize,4]{label=\textperiodcentered}
\setlist[itemize,5]{label=\textbullet}
\setlist[itemize,6]{label=\textendash}
\setlist[itemize,7]{label=\textasteriskcentered}
\setlist[itemize,8]{label=\textperiodcentered}
\setlist[itemize,9]{label=\textbullet}
\setlist[enumerate,1]{label=\arabic*.}
\setlist[enumerate,2]{label=\alph*.}
\setlist[enumerate,3]{label=\roman*.}
\setlist[enumerate,4]{label=\Alph*.}
\setlist[enumerate,5]{label=\arabic*.}
\setlist[enumerate,6]{label=\alph*.}
\setlist[enumerate,7]{label=\roman*.}
\setlist[enumerate,8]{label=\Alph*.}
\setlist[enumerate,9]{label=\arabic*.}
LATEX

    # Give this part its own namespace of hyperlink destinations.
    {
      printf '%% ---- Namespace this part''s hyperlink destinations ----------------\n'
      printf '\\makeatletter\n'
      printf '\\AtBeginDocument{\\renewcommand{\\HyperDestNameFilter}[1]{%s-#1}}\n' "$part"
      printf '\\makeatother\n'
    } >>"$build_dir/header-$part.tex"
  done
}

# ---------------------------------------------------------------------------
# Print the actionable part of a Quarto log: the (ERROR) line and the few lines
# that explain it, instead of the JavaScript stack trace that follows.
report_quarto_log() {
  local log="$1" line
  [[ -f "$log" ]] || return 0
  line="$(grep -n -m1 -E '\(ERROR\)' "$log" | cut -d: -f1 || true)"
  if [[ -n $line ]]; then
    sed -n "$((line > 2 ? line - 2 : 1)),$((line + 5))p" "$log" >&2
  else
    tail -n 12 "$log" >&2
  fi
}

# Isolated copy of the pages to build
# ---------------------------------------------------------------------------

# Quarto writes the LaTeX auxiliary files (index.tex, index.log, index.aux, ...)
# into the directory that holds the source file. Rendering the real pages would
# therefore write into syllabus/ and schedule/, with two bad consequences:
#
#   * two builds that overlap, or a build that overlaps a running
#     "quarto preview", clobber each other's auxiliary files. The failure then
#     looks like "compilation failed" or like a missing index.log, which says
#     nothing about the real cause;
#   * every PDF build touches the site's source tree.
#
# Building an isolated copy keeps every intermediate file inside the working
# directory, so concurrent builds cannot interfere with each other.
prepare_build_tree() {
  local build_dir="$1" part

  # Shortcodes such as iconify come from the project's extensions.
  ln -s -- "$PROJECT_ROOT/_extensions" "$build_dir/_extensions"

  for part in "${PARTS[@]}"; do
    mkdir -p -- "$build_dir/$part"
    cp -- "$PROJECT_ROOT/$part/index.qmd" "$build_dir/$part/index.qmd"
  done
}

# Render one part to PDF
# ---------------------------------------------------------------------------

render_part() {
  local build_dir="$1" part="$2"
  local qmd="$build_dir/$part/index.qmd"
  local log="$build_dir/quarto-$part.log"
  local expected="$build_dir/$part.pdf"
  local -a args=(
    render "$qmd"
    --to "$PDF_FORMAT"
    --output "$part.pdf"
    -M "include-in-header:$build_dir/header-$part.tex"
    --log "$log"
  )

  step "Rendering $part/index.qmd -> $part.pdf"

  if ! $VERBOSE; then
    args+=(--quiet)
  fi

  # Run from the working directory so that every path Quarto resolves, including
  # the ones it mirrors from the input path, stays inside it. The subshell keeps
  # that directory change out of the rest of the script.
  if ! (cd -- "$build_dir" && quarto "${args[@]}"); then
    printf '\n' >&2
    report_quarto_log "$log"
    die "Quarto failed to render $part/index.qmd (full log: $log)"
  fi

  # Belt and braces: the rendering succeeded, so find the PDF wherever Quarto
  # decided to put it and move it to the name the rest of the script expects.
  if [[ ! -f $expected ]]; then
    local found
    found="$(find "$build_dir" -type f -name "$part.pdf" -print -quit)"
    [[ -n $found ]] && mv -- "$found" "$expected"
  fi

  if [[ ! -f $expected ]]; then
    printf '\n' >&2
    warn "Quarto exited successfully but produced no PDF"
    report_quarto_log "$log"
    printf '    Files in %s:\n' "$build_dir" >&2
    ls -1 "$build_dir" 2>/dev/null | sed 's/^/      /' >&2
    die "no $part.pdf was produced (full log: $log)"
  fi
}

# ---------------------------------------------------------------------------
# Join the parts, then verify the result
# ---------------------------------------------------------------------------

# NOTE: the merge itself and every check on the merged file happen in this one
# Python step, so a file is never reported as good without having been read
# back and inspected.
merge_and_verify() {
  local output="$1"
  shift

  PDF_TITLE="$PDF_TITLE" PDF_AUTHOR="$PDF_AUTHOR" PDF_SUBJECT="$PDF_SUBJECT" \
    uv run --quiet --with "$PYPDF_REQUIREMENT" python - \
    "$output" "$@" <<'PYTHON'
"""Join the rendered parts into one PDF and check that nothing broke.

The checks matter more than the merge: a PDF merge can succeed while silently
dropping bookmarks, resolving colliding destination names to the wrong page, or
turning internal links into references to the original files. Every one of
those failures leaves a file that looks fine until a reader clicks a link.
"""

import os
import sys

from pypdf import PdfReader, PdfWriter

output_path = sys.argv[1]
input_paths = sys.argv[2:]


def page_of(reader, dest):
    """Return the 1-based page number a named destination points at."""
    page = dest.get("/Page")
    if page is None:
        fallback = dest.get("/D")
        if isinstance(fallback, list) and fallback:
            page = fallback[0]
    if page is None:
        return None
    try:
        return reader.get_page_number(page) + 1
    except Exception:
        return None


def count_bookmarks(items):
    """Count outline entries, which pypdf exposes as nested lists."""
    total = 0
    for item in items:
        total += count_bookmarks(item) if isinstance(item, list) else 1
    return total


# --- join ------------------------------------------------------------------
writer = PdfWriter()
bounds = []
for path in input_paths:
    first = len(writer.pages) + 1
    writer.append(path, import_outline=True)
    bounds.append((first, len(writer.pages)))

writer.add_metadata(
    {
        "/Title": os.environ.get("PDF_TITLE", ""),
        "/Author": os.environ.get("PDF_AUTHOR", ""),
        "/Subject": os.environ.get("PDF_SUBJECT", ""),
    }
)

with open(output_path, "wb") as handle:
    writer.write(handle)

# --- verify ----------------------------------------------------------------
reader = PdfReader(output_path)

destinations = {
    name: page_of(reader, dest) for name, dest in reader.named_destinations.items()
}

internal = external = 0
mis_targeted = []
for number, page in enumerate(reader.pages, 1):
    for annotation in page.get("/Annots") or []:
        obj = annotation.get_object()
        if obj.get("/Subtype") != "/Link":
            continue
        action = obj.get("/A")
        if action is None:
            continue
        action = action.get_object()
        kind = action.get("/S")

        if kind == "/URI":
            external += 1
            continue
        if kind != "/GoTo":
            continue

        internal += 1
        raw_target = action.get("/D")
        if isinstance(raw_target, str):
            target = destinations.get(raw_target)
        elif isinstance(raw_target, list) and raw_target:
            target = page_of(reader, {"/D": raw_target})
        else:
            target = None

        # The link must stay inside the part it was authored in; a target in the
        # other part means a destination name collided during the merge.
        low, high = next(
            (low, high) for low, high in bounds if low <= number <= high
        )
        if target is None or not low <= target <= high:
            mis_targeted.append((number, action.get("/D"), target))

bookmarks = count_bookmarks(reader.outline)

print(f"   pages          {len(reader.pages)}")
for path, (low, high) in zip(input_paths, bounds):
    print(f"     {os.path.basename(path):<22} {high - low + 1:>3}  (pages {low}-{high})")
print(f"   bookmarks      {bookmarks}")
print(f"   internal links {internal}  (mis-targeted: {len(mis_targeted)})")
print(f"   external links {external}")

if mis_targeted:
    print("\n   Broken internal links:", file=sys.stderr)
    for number, name, target in mis_targeted:
        print(f"     page {number}: {name!r} -> {target}", file=sys.stderr)
    sys.exit(1)
PYTHON
}

join_parts() {
  local build_dir="$1" output="$2"
  shift 2
  local -a inputs=("$@")
  local merged="$build_dir/merged.pdf"
  local err="$build_dir/pypdf.err"
  local status=0

  step "Joining ${#inputs[@]} parts into ${output##*/}"

  # Merge into the working directory and only publish the result once it has
  # been verified, so a bad merge can never replace a good PDF.
  if ! merge_and_verify "$merged" "${inputs[@]}" 2>"$err"; then
    status=1
  fi

  # pypdf prints a harmless "Annotation sizes differ" note for some LaTeX
  # documents, so keep that line out of the output unless the merge failed.
  if [[ -s "$err" ]]; then
    if ((status == 0)); then
      if grep -qv 'Annotation sizes differ' "$err"; then
        grep -v 'Annotation sizes differ' "$err" >&2 || true
        warn "the merged PDF was written, but pypdf reported the notes above"
      fi
    else
      cat "$err" >&2
    fi
  fi

  if ((status != 0)); then
    if [[ -e "$output" ]]; then
      die "joining the parts failed; $output was left untouched (full log: $err)"
    fi
    die "joining the parts failed (full log: $err)"
  fi

  mv -- "$merged" "$output"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
  preflight

  BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/syllabus-pdf.XXXXXX")"

  cleanup() {
    # The EXIT trap runs after main() has returned, so only look at globals.
    [[ -n ${BUILD_DIR:-} && -d ${BUILD_DIR:-} ]] || return 0
    if $KEEP_INTERMEDIATES; then
      printf ' %s  Intermediate files kept in %s\n' "$ICON_FILE" "$BUILD_DIR" >&2
    else
      rm -rf -- "$BUILD_DIR"
    fi
  }
  # shellcheck disable=SC2064
  trap cleanup EXIT

  local started=$SECONDS
  local build_dir="$BUILD_DIR"

  write_headers "$build_dir"
  prepare_build_tree "$build_dir"

  local -a pdfs=()
  local part
  for part in "${PARTS[@]}"; do
    render_part "$build_dir" "$part"
    pdfs+=("$build_dir/$part.pdf")
  done

  local output_dir="${OUTPUT%/*}"
  [[ $output_dir == "$OUTPUT" ]] && output_dir="."
  mkdir -p -- "$output_dir"
  join_parts "$build_dir" "$OUTPUT" "${pdfs[@]}"

  local size
  size="$(du -h -- "$OUTPUT" | cut -f1)"

  printf '\n' >&2
  ok "Wrote $OUTPUT ($size, built in $((SECONDS - started))s)"

  if $KEEP_INTERMEDIATES; then
    info "Per-part PDFs: $build_dir/*.pdf"
  fi

  if $OPEN_AFTER; then
    if command -v xdg-open >/dev/null 2>&1; then
      xdg-open "$OUTPUT" >/dev/null 2>&1 &
    else
      warn "xdg-open is not available, open the PDF manually"
    fi
  fi
}

main
