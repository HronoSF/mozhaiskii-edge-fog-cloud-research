# Unchanged report typography

`research-report.sty` and `research-report.tex` are retained byte-for-byte from the approved public template: A4, 25 mm margins, Latin Modern, 1.15 line spacing, plain booktabs tables and centered page numbers. Do not redesign them when updating data.

`../report/scheduling-report.md` is the report content. `../scripts/build_report.py` turns the public CSVs into versioned, indivisible table floats and generates `../report/scheduling-report.tex` with Pandoc using this template. XeLaTeX builds the PDF; SVGs are converted to vector PDF with CairoSVG. Run `make` from the repository root. Inspect every rendered page, table and chart before publishing. No Word/HTML substitute or direct PDF editing.
