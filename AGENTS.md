# Security Synapse Agent Instructions

This document provides instructions for coding and writing agents working on
the Quarto-based website for Security Synapse.

## Project Identity

- The website is for Computer Science 403, a computer security course.
- The public website is https://www.securitysynapse.org/.
- The course connects high-level security concepts to low-level implementations.
- Students make a "security synapse" by connecting concepts, source code,
  experiments, and evidence.
- The primary course texts include *Computer Systems Security: Planning for
  Success* (CSP), *Cracking Codes with Python* (CCP), *The Joy of Cryptography*
  (JOY), and *Operating Systems: Three Easy Pieces* (OSTEP).
- Week Two uses Chapter 1 of CSP. Its central ideas include risk management,
  CIA, AAA, DRY, PDR, threat actors, security plans, controls, user awareness,
  backups, and encryption.

## General Principles

- Maintain the existing Markdown and Quarto style of this repository.
- Make small, reviewable changes instead of rewriting unrelated content.
- Preserve the author's phrasing when it is already clear and effective.
- Do not introduce content merely to fill space.
- Keep examples accurate, beginner-friendly, practical, and professionally
  written.
- Do not commit changes unless the user explicitly asks for a commit.
- Before editing, run `git status --short` and avoid changing unrelated files.
- If the user is editing other files concurrently, modify only the requested
  paths.
- Use the pi todo tools to track multi-step work and keep the parent task open
  until every requested requirement is complete.

## Site Structure

- Website configuration: `_quarto.yml`
- Course syllabus: `syllabus/index.qmd`
- Course schedule: `schedule/index.qmd`
- Slide decks: `slides/<week>/index.qmd`
- Slide-specific CSS: `slides/css/styles.css`
- Website-wide CSS: `css/styles.css`
- Synthetic Week Two data: `slides/weektwo/security.json`
- Synthetic corrupted data: `slides/weektwo/security-corrupted.json`
- Generated output in `_site/`, `_freeze/`, and `*.quarto_ipynb` files is
  ignored and should not be edited or committed.

## Editing Quarto Pages

1. Read the target file and the relevant syllabus or schedule entry first.
1. Read nearby content and at least one comparable page before adding new
   material.
1. Use the Edit tool for precise changes and the Write tool only for genuinely
   new files.
1. Keep Markdown and source-code lines at or below 80 characters where
   practical. Browser layout is a separate constraint from source line width.
1. Use single backticks for source-code names such as `compute_hash`.
1. Use fragments and incremental lists intentionally, not on every element.
1. Keep each bullet focused on one idea.
1. Do not normally put periods at the end of bullet points. Use periods when a
   bullet contains multiple complete sentences or when punctuation is needed
   for clarity.
1. Support important claims with the assigned textbook, syllabus, code output,
   or a clearly identified external source.

## Creating and Editing Reveal.js Slides

- Week Two uses `revealjs` with `jupyter: python3`.
- A `{python}` fence is executed by the Quarto/Jupyter environment.
- A plain `python` fence is displayed but not executed. This is appropriate
  for intentionally unsafe examples that must not run, such as an infinite
  loop demonstrating resource exhaustion.
- The available Python environment includes Python 3.11, `cryptography`,
  `jupyter`, `rich`, and the standard library. Do not add dependencies unless
  they are genuinely needed and approved.
- Use the existing slide CSS and conventions rather than adding a global font
  reduction to solve a single crowded slide.
- A slide title should normally fit on one browser line. If two lines are
  necessary, both lines should be useful and visually balanced.
- Prefer concise titles such as "Dictionary Attack" or "ACL: Least Privilege"
  over titles that describe an entire paragraph.
- When a level-one heading is used as a section divider, put the actual content
  on a following level-two slide. This avoids the title slide and its content
  overlapping in reveal.js.
- Keep a code slide to a readable amount of source, usually about 10--16
  visible lines. If a code example needs more, split it across slides instead
  of shrinking it until it is unreadable.
- Keep code lines short enough to fit the code block without horizontal
  clipping. Break long lists, calls, and dictionaries across lines.
- Show enough output to explain the example, but do not print entire encrypted
  files, huge logs, or repetitive output.
- Every code example should be followed by a concise takeaway or discussion
  question.
- Use `.boxed-content` for one short key message or question. Do not put a
  paragraph or a second list inside a takeaway box.
- A slide should either use two useful lines for a bullet or shorten the bullet
  to one line. Avoid a second line containing only one or two words.
- Avoid nested columns unless they clearly improve the explanation. When column
  widths are needed, put the width and font size in one `style` attribute; do
  not combine a `width` attribute with a `style` attribute because Quarto can
  emit duplicate-attribute warnings.
- Use icons sparingly and only when they clarify the message. Use the existing
  Iconify shortcode style, for example:
  `{{< iconify fa6-solid lightbulb >}}`.

### Narrative Signposting

Use a deliberate three-part teaching rhythm throughout a slide deck:

1. **Tell them what you will tell them**: begin a section with a concise
   signpost that previews the concepts, examples, or questions that follow
2. **Tell them**: teach the concepts and show the implementation without
   repeating the preview on every slide
3. **Tell them what you told them**: close the section with a concise summary
   that maps the examples back to the main concepts

- A preview signpost should identify what is coming and why it matters
- A recap signpost should identify what was learned and how the pieces connect
- Keep signposting slides concise; they should orient learners, not become a
  second lecture
- Use a level-one heading only as a short section divider, then put the preview
  or teaching content on a level-two slide
- Do not create a redundant recap when a nearby slide already summarizes the
  same material
- For code sections, preview the security concepts first, show the code and
  output next, and end with a summary that connects the behavior to the
  vocabulary from the assigned reading

## Week Two Content Rules

- Week Two should visibly connect code to CSP Chapter 1.
- The main concept vocabulary is CIA, AAA, PDR, DRY, risk, threat actor,
  vulnerability, attack, impact, security plan, and controls.
- Use the synthetic vulnerability inventory as teaching data. Label it as
  synthetic; do not imply that its fictional CVE records are real.
- A realistic authentication example should model a recognizable workflow,
  such as credential stuffing, an authentication event log, rate limiting, or
  account lockout. Do not present a hard-coded password comparison as a
  production authentication design.
- Authorization examples should show identity, resource, action, and a
  deny-by-default or least-privilege decision.
- Availability examples should distinguish recovery from confidentiality and
  integrity. A backup does not undo data theft or repair the original flaw.
- Use toy data and safe simulations. Never include real credentials, secrets,
  destructive commands, or code that attacks an external system.

## Browser-Based Slide Verification

Textual inspection alone is not enough for slide work. Verify the rendered
browser layout.

1. Check whether a preview server is already running. This project normally
   uses port 5559, as configured in `_quarto.yml`.

1. If preview is running, let it rebuild the page and verify it with:

   ```bash
   curl -fsS http://localhost:5559/slides/weektwo/ >/tmp/weektwo.html
   ```

1. Otherwise render the target deck from the repository root:

   ```bash
   uv run quarto render slides/weektwo/index.qmd --to revealjs
   ```

1. Use Chromium at a real presentation size, such as 1600x900, for screenshots.

1. For visual QA, temporarily reveal hidden fragments in a temporary copy of
   the rendered HTML. Never modify the generated HTML as a project change.

1. Check both viewport overflow and intentional line wrapping. A useful browser
   measurement is:

   ```javascript
   const range = document.createRange();
   range.selectNodeContents(element);
   const lines = [...range.getClientRects()];
   ```

   Multiple rectangles indicate that the element wraps. Inspect whether the
   second rectangle contains useful content or only a stranded word.

1. For each slide, compare `scrollWidth` with `clientWidth` and `scrollHeight`
   with `clientHeight`. Any meaningful excess requires a content or layout fix.

1. Check code blocks, output, titles, fragments, columns, and takeaway boxes at
   the same browser size. Do not infer layout quality from source line counts
   alone.

1. Remove all temporary screenshots, debug HTML, and inspection files after
   verification. Keep only intentional source files and user-requested
   backups.

### Important Render Workflow Detail

The Quarto execution notebook can be regenerated by both `quarto preview` and
`quarto render`. Running them simultaneously can produce an intermittent
`index.quarto_ipynb` "No such file" error. Do not delete the generated notebook
while preview is active. Prefer allowing the existing preview server to rebuild,
or stop it deliberately before running a standalone render.

## Code Quality

- Put imports at the top of an executable code segment.
- Use type hints for functions when they improve clarity.
- Use `pathlib.Path` for filesystem operations in new examples.
- Use specific exceptions when error handling is needed.
- Do not log passwords, encryption keys, or sensitive plaintext.
- Keep executable examples bounded and deterministic enough to render reliably.
- Avoid network access, interactive prompts, infinite loops, and unbounded
  output in executed cells.
- If an unsafe example is pedagogically necessary, display it in a plain fence,
  label it clearly, and explain why it is not executed.

## Completion Checklist

Before reporting completion:

- [ ] The requested file(s) are the only source files changed, apart from any
  explicitly requested backup or instruction files.
- [ ] The original wording and formatting were preserved where appropriate.
- [ ] Every new claim is supported by course material, code behavior, or a
  cited source.
- [ ] Every executed Python cell runs in the configured environment.
- [ ] Code output is bounded and useful.
- [ ] Titles fit on one line or use two balanced lines.
- [ ] Bullets do not strand one or two words on a second line.
- [ ] Code does not clip horizontally or run below the footer.
- [ ] Takeaway boxes fit within the slide and contain one concise message.
- [ ] The rendered deck and browser preview are reachable.
- [ ] `git diff --check` passes.
- [ ] No commit was made unless explicitly requested.
- [ ] Temporary QA files have been removed.
- [ ] The relevant pi todo remains open if the user requested a review
  checkpoint before the whole task is complete.
