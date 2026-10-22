# Edge-Fog-Cloud scheduling: three fresh VM runs

Gleb Mozhaiskii - personal preliminary research related to prospective doctoral studies at UPV/EHU. This is not an official university publication.

**[Read the updated report (PDF)](report/UPV-EHU_Scheduling_Report_A01-A03.pdf)** · [Report source](report/scheduling-report.md) · [Execution instructions](experiment/README.md)

An application orchestrator assigns real CPU tasks to Edge, Fog and Cloud workers with different CPU quotas and explicit queues. [MADT](https://github.com/dltcspbu/madt) controls the routed network. Each session uses one fresh Linux VM containing four Docker containers, not four physical sites.

## This release

The report presents **three fresh VM runs**. In the measurement files, the immutable source IDs A01, A02 and A03 correspond to reader-facing Run 1, Run 2 and Run 3; this display mapping does not rename an experiment. Three sequential fresh ARM64 Lima VM sessions each ran the same 12 scenarios once: Round Robin, Compute-ECT and Network-ECT; steady and burst arrivals; unshaped networking and nominal 20 ms extra one-way Cloud ingress delay.

| Session | Correct worker outputs, including preparation | Scored on time / offered | Application / network |
|---|---:|---:|---|
| Run 1 |948|144/144|Complete / IN_SPEC|
| Run 2 |948|144/144|Complete / IN_SPEC|
| Run 3 |948|143/144|Complete / IN_SPEC|

All 432 scored tasks returned correct answers. The one late Run 3 Round Robin/burst/unshaped Edge task took1002.317940 ms from planned arrival, exceeding the 1 s SLO by2.317940 ms. It is retained. All three evidence exports and scoped VM cleanups were verified.

![Per-session scenario medians](figures/median-latency.svg)

The unit of replication is the **VM session: N=3 on one physical host**. Tasks and scenarios are nested measurements. Timings and placements vary; these data establish a bounded correctness screen, not general platform reliability, physical multi-site realism or scheduler superiority. ECT decision overhead was higher than matched RR in all observed median contrasts; response medians alone do not establish a winner.

## Data and source

- [36 scenario rows](data/scenario-results.csv): every session, policy and condition; outcomes, placements, timing distributions and rates.
- [432 scored tasks](data/scored-tasks.csv): all offered scored outcomes and elapsed timing components. Timestamps are offsets from the first planned arrival in the same cell.
- [2,844 worker completions](data/worker-completions.csv), [all-node accounting](data/node-results.csv), [three session summaries](data/session-results.csv).
- [Effective execution inputs and package pins](experiment/): 34 byte-identical runtime/support files from the common 38-file capture, plus the original scoped VM lifecycle runner.
- [Source identities](experiment/SOURCE.json), [input hashes](experiment/INPUTS.sha256.json) and [release file hashes](MANIFEST.sha256).

Measured execution revision: `b47689f644397018d408e97f83be5c587d7182ff`. Audited results revision: `33035e085988ce2165fdd46755ee8f75cb3a04e4`. These identifiers bind the provenance; public packaging is subsequent and does not repeat acquisition. The recorded cohort received independent raw-evidence scientific review. The public export contains measurement tables, not the full private host/authority logs or internal reviews. Research hypotheses, debugging and historical cohorts are maintained separately.

## Rebuild the report offline

Use Python 3, Pandoc and XeLaTeX (TeX Live with Latin Modern and the packages in `latex/research-report.sty`). CairoSVG also requires Cairo. On Apple Silicon with Homebrew Cairo, the Makefile uses `/opt/homebrew/lib`; override `CAIRO_LIBDIR` if Cairo is installed elsewhere. No VM or Docker is needed for these commands:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-report.txt
make PYTHON=.venv/bin/python
make verify PYTHON=.venv/bin/python
```

The shared LaTeX template/style is unchanged. The topology image is extracted unchanged from the supplied reference PDF; it replaces the different diagram that had been in this repository. Tables use indivisible `tabular` floats: a complete table moves to the next page if necessary. Colored SVG figures regenerate from the checked-in CSVs. The report body is available in both readable Markdown and complete generated LaTeX. Rebuilding need not produce an identical PDF binary across TeX versions; source/data hashes and numerical content are checked.

A new experiment is a separate privileged operation; see [the execution guide](experiment/README.md). **No new VM was launched for this publication.** The packaged public entrypoint has been checked offline, not independently rerun in another VM. Do not count an offline build as an experimental replication.

## Context

Wang et al. (2026), [DOI 10.1109/ICDCSW72724.2026.00054](https://doi.org/10.1109/ICDCSW72724.2026.00054), informs matched comparisons, service-level accounting and decision-overhead measurement. This CPU-task experiment does not reproduce their multi-mode AI benchmark. Upstream MADT and tcconfig retain their own licenses; the tcconfig patch attribution/license is included. No new general software license is asserted by this publication.
