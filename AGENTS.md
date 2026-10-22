# Research publication instructions

Write scientific explanations in plain English, defining Edge, Fog, Cloud, ECT, MADT and other technical terms before first use. Use a simple hyphen `-` rather than typographic en/em dashes in prose, and straight single quotes `'...'` instead of curly quotation marks. Retain precise measured results and clear limitations.

## PDF publication rule

Any future PDF must be built from complete, versioned LaTeX source with XeLaTeX, using the shared templates `latex/research-report.tex` and `latex/research-report.sty`. Keep every plotted measurement and figure under version control. Match the validated reference report before publishing and inspect every rendered chart, table and page.

The previously published Markdown report and compiled PDF were withdrawn because that separate conversion had not been validated against the approved local PDF. Do not reconstruct or publish a substitute report automatically; publication requires verified document sources and rendered output.

Do not create canonical PDF artifacts via Word, browser print, WeasyPrint or manual drawing; do not edit generated PDFs directly. Check font embedding, accessibility of links, actual graphic rendering, tables and page breaks. No font binaries in the repository.

Do not silently change data or convert pilot observations into claims of cross-session repeatability or a scheduler-performance ranking. Do not include proprietary logs, private repository history, host identifiers, token/secrets or unpublished internal reviews in the public release.
