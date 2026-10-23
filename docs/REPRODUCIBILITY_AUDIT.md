# Public cleanup and reproducibility audit

Scope: a packaging-only cleanup based on reviewed public commit `4073a282e3008c6c42556cac382e07b0e89346fa`. The original acquisition, algorithms, workloads, deadlines, thresholds and results are unchanged. No VM, guest root operation, host Docker/network change or new experiment is part of this audit. Independent review of the final cleanup SHA is recorded in the cleanup PR discussion; author checks are not independent approval.

## File-by-file changes

| File | Change and reason |
|---|---|
| `README.md` | Three Quick Starts: reading, rebuilding, and new acquisition/verification; prerequisites, outputs and limitations. |
| `experiment/README.md` | Explicit macOS ARM64-only runner/Python requirement; fresh-output verification and status interpretation. |
| `latex/README.md` | Explain separate build output and source comparisons. |
| `scripts/export_a_data.py` | Removed: depended on unavailable private reviewed TSV projections. Not used by report building or acquisition. The five published CSVs remain canonical input data. |
| `scripts/verify_session.py` | New standard-library offline checker for a full runner output directory, with readable and JSON domain results. |
| `tests/synthetic_session.py` | Invented test fixtures only, using deterministic reference task outputs. No raw acquisition/host logs are published. |
| `tests/test_verify_session.py` | Positive and adversarial checks for missing/corrupt/incomplete data, raw/source consistency, export, network, resources and cleanup. |
| `tests/test_release_integrity.py` | Synthetic negative checks for missing/duplicate/unsafe/changed release manifests and unintended copied inputs. |
| `scripts/verify_release.py` | Retain historical CSV checks; additionally require a nonempty safe release manifest, unchanged host runner and exact copied payload inventory. |
| `scripts/generate_figures.py` | Default output becomes `build/generated/figures/`; calculations, palette and geometry remain unchanged. |
| `scripts/build_report.py` | Generate tables/LaTeX in `build/generated/` and compare all generated sources with canonical files. |
| `Makefile` | Build `build/scheduling-report.pdf` without replacing the canonical PDF; expose test/report-verification targets. |
| `scripts/verify_report.py` | Check rebuilt nine-page text/geometry, whole tables, embedded fonts and retained links. Rendered-page inspection remains required. |
| `requirements-report.txt` | Pin the complete tested Python report-build dependency set; separate from frozen acquisition locks. |
| `docs/VERIFYING_A_SESSION.md` | Exact checker scope, statuses, exit codes, resource bounds and unverified scientific/live-teardown claims. |
| `docs/LICENSING.md` | Upstream notices/unknowns and proposed original-work licenses, without assigning one. |
| `docs/REPRODUCIBILITY_AUDIT.md` | This public audit summary. |
| `MANIFEST.sha256` | Refresh the public snapshot inventory; acquisition input hashes do not change. |

The PDF, complete report LaTeX, Markdown body, nine tables, four figures, five CSVs, shared template/style, 34 pinned runtime/support files, original host runner and acquisition source metadata remain byte-identical. Keeping PDF/Markdown/LaTeX/SVG alongside each other is intentional: they serve reading, inspection and reproducible building, not duplicate historical experiments. Frozen support/diagnostic files remain because the original runner copies that payload; removing them would change the recorded input contract. Historical host stages are not promoted as public entrypoints.

## Public execution path inspection

`clone -> local prerequisites -> offline checks -> fresh owned Lima VM -> pinned guest preparation -> health qualification -> application pilot -> one-shot export -> scoped VM deletion -> offline output verification` was traced through the published runner, supervisor, guest scripts and original entry adapters. Root operations occur only in the new Linux guest. The runner downloads/validates its Lima and Ubuntu assets and refuses an existing output slot. Inputs resolve within this public tree; no private wrapper, plan or TSV export is needed to execute it.

There are two important operational constraints. First, `--stage calibration` actually runs health checks followed by the complete scheduling pilot; the historical stage names `full`/`timing` must not be used with this payload. Second, exact package/image pins can become unavailable. This repository is not an offline package mirror, and the unpatched expected-failure control deliberately fails if upstream behavior no longer matches its recorded defect. Preserve that failure; do not silently substitute packages or relax a criterion.

Offline release checks also detect extra untracked files in the `experiment/compat` and `experiment/tests` trees, which the unchanged runner would otherwise copy into its input manifest. Run from a clean checkout. Python bytecode cache directories are excluded by both runner and checker.

## Validation and limits

Author checks on macOS 27.0.1 ARM64: Python 3.14.7 for standard-library checks; Python 3.12.14 with the pinned report dependencies for PDF building; Pandoc 3.9.0.2; portable TeX Live 2026/XeTeX 0.999998 and Cairo. No system TeX installation or font binaries were added to this repository.

The original 22 scheduling unit tests and 55 new synthetic tests pass (77 total). The new synthetic suite exercises successful bounded verification and adverse/missing evidence; the independently executed commands and final review SHA are recorded in the PR discussion. The published release verifier and runner/verifier `--help` are exercised without launching a VM. The public checker was additionally applied read-only to an existing historical A03 directory: 948 correct worker outputs, 144 comparison offers, 143 on time, original network bounds and consistent saved cleanup records. Full scientific eligibility correctly remains UNVERIFIED. That optional author cross-check uses nonpublic historical archives; public tests, building and new-output verification do not depend on access to them.

The report rebuild regenerated byte-identical SVGs, nine table files and complete LaTeX. The resulting nine pages have exact extracted text/page geometry, embedded fonts, unchanged links and matching whole-table labels; all nine rendered pages are pixel-identical to the canonical report at 85 dpi and were visually inspected. The canonical PDF remains SHA-256 `6debdbbd00e68580a0910e15f4a7fc5a971c197d800e96c0ad25b72d8050febb`. The rebuild has different PDF bytes because metadata/encoding are not fixed; no content was changed to force binary equality.

Author setup attempts included an incorrect archival TinyTeX asset URL returning 404, then selection/hash verification of the official versioned Darwin archive. The TeX package installer returned nonzero for `array`, `calc` and `longtable` requested as standalone package names; those files are supplied by the existing TeX `tools` package. Required files were available and compilation passed. No failed command is claimed as successful installation. The first historical verifier pass rejected the original 38-file capture; explicit acceptance of its four already documented omitted context hashes was added, while retaining the strict 34-file public payload path. An author adversarial check also found malformed JSON object/field types could raise an uncaught AttributeError instead of returning a structured domain failure. The domain boundary now records FAIL for this case; two regressions cover malformed host/resource records. The separate reviewer also found false PASS cases for explicit source/worker error events, failed health status and wrong hello/probe identities. These are now rejected, with consistent shutdown summaries, original qualification completion receipts and message identities checked against the pinned schema. Further regressions reject boolean values masquerading as integer seeds/profile estimates. One updated negative-test filter initially assumed every network event had a description; it was corrected to preserve and handle the newly required gate event. The failed test log is retained outside the public tree. Final recheck additionally found that the original health CLI exit had not been bound to qualification success/failure. It is now required to be the exact integer 0/1 specified by the frozen adapter. Logged gate fields are reconciled at their six-measurement acquisition prefix, and the final health completion receipt against all seven measurements/checks. Regressions also preserve the legitimate numerical-failure/exit-one case as separate from application correctness. New checker/adversarial tests are synthetic; they are not new experimental outcomes.

## Before public release

A separately authorized clean-room VM acquisition using only this public package is still outstanding. Offline inspection cannot prove current remote package availability or successful guest execution. Linux-host/Windows VM execution is not implemented. Three old same-host VM sessions do not establish general reliability.

The public checker is deliberately narrower than the original full independent scientific audit. It does not certify every route/interface/qdisc command, replay every causal decision, authenticate self-reported logs or independently observe actual host teardown. A PASS does not grant final scientific performance eligibility. Missing cleanup/export or failed network conditions cannot be promoted to eligibility.

Original-work license selection still needs owner approval. The tcconfig MIT notice is preserved. No explicit license file was found at the pinned MADT revision; clarify upstream redistribution rights before vendoring its code. See the licensing audit. No history rewrite, automatic merge or release publication is performed.
