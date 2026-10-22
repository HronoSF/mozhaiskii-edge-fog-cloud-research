# Research publication instructions

Write scientific explanations in plain English, defining Edge, Fog, Cloud, ECT, MADT and other technical terms before first use. Use a simple hyphen `-` rather than typographic en/em dashes in prose, and straight single quotes `'...'` instead of curly quotation marks. Retain precise measured results and clear limitations.

## PDF build rule

**Every PDF in this repository must be generated from versioned LaTeX sources using the common template** `latex/research-report.tex` and stylesheet `latex/research-report.sty`. The build path is `report/scheduling-pilot.md` -> Pandoc-generated `.tex` -> XeLaTeX -> PDF, with figures and measurement data committed separately. Use `make` as the canonical build.

Do not create canonical PDF artifacts via Word, browser print, WeasyPrint or manual drawing; do not edit generated PDFs directly. A changed PDF must come from corresponding source changes. Check font embedding, accessibility of links, actual graphic rendering, tables and page breaks. No font binaries in the repository.

Do not silently change data or convert pilot observations into claims of cross-session repeatability or a scheduler-performance ranking. Do not include proprietary logs, private repository history, host identifiers, token/secrets or unpublished internal reviews in the public release.
