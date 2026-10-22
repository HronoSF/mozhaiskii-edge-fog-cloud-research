# Public experiment publication instructions

This repository contains only the A01-A03 report, its measurement tables/figures, effective execution source and instructions. Research planning, hypotheses, debugging, live authority and internal reviews belong in the private development repository.

Write plain English and define technical terms before use. Use ordinary hyphens and straight quotes in prose. Preserve unfavorable outcomes, original deadlines and numerical thresholds. N=3fresh VM sessions on one physical host is a bounded correctness screen, not general reliability or policy superiority.

Build every PDF with XeLaTeX from complete versioned source using `latex/research-report.tex` and `latex/research-report.sty`. Keep their typography unchanged. Keep every plotted measurement and figure versioned. Inspect every rendered page, chart and table against the reference style. Tables must remain whole on one page. Check embedded fonts, links and actual vector rendering. Do not publish font binaries, use Word/browser PDF substitutes or edit generated PDFs.

The 34 published runtime/support input files under `experiment/` are byte-pinned acquisition source. Do not silently modernize or retune them. Public packaging is checked offline; an offline build/test is never a new VM replication. New guest operations require a separately specified/authorized scope, preserve failed/partial attempts and must not overwrite the closed A01-A03 cohort. Never use broad Docker/VM pruning.

Do not publish credentials, host identifiers, proprietary logs, private history or internal review records. Require a separate fresh independent review of final scientific claims and publication artifacts before acceptance. No automatic merging.
