# Security Synapse

This is the GitHub repository for [Security Synapse](https://www.securitysynapse.org/),
a website that provides a centralized place for security researchers to learn,
share their findings, and collaborate with each other.

The website is built with [Quarto](https://quarto.org/) and deployed as a
static-asset [Cloudflare Worker](https://developers.cloudflare.com/workers/).

## Requirements

Install the following tools locally:

- [Quarto](https://quarto.org/docs/get-started/)
- [uv](https://docs.astral.sh/uv/)
- Python 3.11 (the repository pins this version in `.python-version` for
  reproducible builds)

Python dependencies are declared in `pyproject.toml`, resolved in `uv.lock`,
and installed into uv's project environment. At present the site depends on
[cryptography](https://pypi.org/project/cryptography/) — the material on this
site demonstrates Fernet symmetric encryption and asymmetric primitives from
`cryptography.hazmat` — and on `jupyter`, which Quarto uses to execute the
Python code cells throughout the site.

## Initial setup

From the repository root, synchronize the locked dependencies:

```bash
uv sync --locked
```

To update dependencies after changing `pyproject.toml`, run:

```bash
uv lock
uv sync
```

Use `uv add` when adding a dependency so that both `pyproject.toml` and
`uv.lock` remain consistent:

```bash
uv add package-name
uv add --dev development-package-name
```

## Build the website

Render the website with:

```bash
uv run quarto render
```

The generated site is written to `_site/`. The Python code cells in the site
(see `index.qmd` and the `slides/` directory) execute against the project
environment managed by uv, so `cryptography` and `jupyter` are available
without any global installs.

For a development preview, use:

```bash
quarto preview
```

To serve an already-rendered site locally:

```bash
cd _site
python -m http.server 8000
```

## Continuous integration

The GitHub Actions workflow in `.github/workflows/publish.yml` uses uv for the
Python setup: it installs uv, runs `uv sync --locked`, and then invokes Quarto
with `uv run`. Pushes to the `main` branch render the site and deploy it to
Cloudflare Workers.

## Repository layout

```text
_quarto.yml                  Main Quarto configuration
index.qmd                    Site home page
schedule/                    Course schedule
slides/                      Course slides
syllabus/                    Course syllabus
projects/                    Course projects
scripts/migrate-to-cloudflare.py
                             Cloudflare migration helper
scripts/migrate-configs/securitysynapse.toml
                             Site-specific migration settings
pyproject.toml               Project metadata and dependencies
uv.lock                      Locked dependency resolution
wrangler.toml                Cloudflare Worker configuration
```

## License and content

This repository contains educational security course material and supporting
website code. Refer to the individual source files and linked projects for
their applicable licenses and attribution requirements.