# Edge-Fog-Cloud scheduling research

**Gleb Mozhaiskii** | Independent preliminary research related to prospective doctoral studies at the University of the Basque Country (UPV/EHU). **Not an official university publication.**

**Start here:** [Testbed validation note (PDF)](report/UPV-EHU_Testbed_Validation_Note.pdf) | [Measurements](data/) | [Reproduction instructions](experiment/README.md) | [Verification scope](docs/VERIFYING_A_SESSION.md)

An application orchestrator assigns real CPU tasks to Edge, Fog and Cloud workers with explicit queues and different CPU quotas. [MADT](https://github.com/dltcspbu/madt/tree/ca7df8460448ae515f17bfb3a594b30ef9503415) controls the routed network. Each run uses one fresh Linux VM with four Docker containers, on a shared physical host. Edge, Fog and Cloud are logical roles in an emulated network, **not separate physical sites**.

![Gateway, Edge, Fog and Cloud topology](figures/topology.png)

## Quick Start 1: read the recorded results

**[Open the testbed validation note](report/UPV-EHU_Testbed_Validation_Note.pdf)**. No software installation is needed. Its [Markdown](report/testbed-validation-note.md) and [complete LaTeX](report/testbed-validation-note.tex) are versioned. The [previous scheduling-report iteration](report/UPV-EHU_Scheduling_Report_A01-A03.pdf) remains available, with its [Markdown](report/scheduling-report.md) and [complete LaTeX](report/scheduling-report.tex). [Figures](figures/) and [five measurement CSVs](data/) are versioned.

| Run | Correct outputs, including preparation | Scored tasks on time / offered |
|---|---:|---:|
| Run 1 |948|144/144|
| Run 2 |948|144/144|
| Run 3 |948|143/144|

All 432 scored tasks returned correct answers. The retained late Round Robin/burst/normal-network Edge task took 1002.317940 ms from planned arrival, exceeding the original 1 s deadline by 2.317940 ms. Network checks, exports and cleanups passed the original cohort's separate audit.

The unit of replication is **one fresh VM session: three sessions on one physical host**. The 12 scenarios combine Round Robin, Compute-ECT and Network-ECT; steady/burst arrivals; normal networking/nominal 20 ms extra one-way Cloud ingress delay. They are nested measurements, not 36 independent replications. ECT decision overhead was higher in all observed matched median contrasts. These results do not establish policy superiority or general platform reliability.

The immutable file keys A01/A02/A03 map to Run 1/2/3. The [36 scenario rows](data/scenario-results.csv), [432 scored-task rows](data/scored-tasks.csv), [2,844 worker outputs](data/worker-completions.csv), [all-node counts](data/node-results.csv) and [three session summaries](data/session-results.csv) are publication tables, not full acquisition archives. Raw host logs, approvals and internal reviews are not public inputs.

## Quick Start 2: rebuild and check the report

Clone the published default branch:

```sh
git clone https://github.com/HronoSF/mozhaiskii-edge-fog-cloud-research.git
cd mozhaiskii-edge-fog-cloud-research
```

Offline integrity and scheduling/checker tests need **Python 3.12 or newer** and its standard library only:

```sh
python3 scripts/verify_release.py
make test PYTHON=python3
python3 experiment/run_session.py --help
```

The PDF build additionally needs Make, Pandoc, XeLaTeX/TeX Live, Cairo and the pinned Python packages. TeX must provide the packages listed in [the shared style](latex/research-report.sty), Latin Modern fonts and `newunicodechar`. Charts require Georgia and Times New Roman through Cairo/fontconfig; font binaries are not distributed. The audited build uses macOS 27.0.1 ARM64, Python 3.12.14, Pandoc 3.9.0.2 and TeX Live 2026. Other report-build platforms/toolchains are not verified here. The canonical PDF remains readable everywhere with a PDF reader.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-report.txt
make PYTHON=.venv/bin/python
make report-verify PYTHON=.venv/bin/python
make verify PYTHON=.venv/bin/python
```

**Rebuilt PDF: `build/testbed-validation-note.pdf`.** The canonical PDF and versioned sources are never overwritten by this workflow. Regenerated tables, LaTeX and SVGs appear under `build/generated/` and are compared with the versioned sources before compilation. Rebuilding uses no VM, Docker or private files. Package installation needs Internet; the subsequent build uses local inputs.

On Apple Silicon with Homebrew Cairo the Makefile uses `/opt/homebrew/lib`; set `CAIRO_LIBDIR` for a different Cairo installation. Set `XELATEX` to an explicit compiler path if necessary. Report verification checks the canonical page count, exact per-page text/geometry, whole tables, embedded fonts and links. Different PDF metadata or encoding can change bytes; inspect rendered pages before accepting a different toolchain. Do not alter scientific values or typography to force a matching hash.

## Quick Start 3: collect and verify a new session

**VM execution supports macOS ARM64 only**, using Apple's Virtualization.framework. There is no implemented/verified Linux-host or Windows runner. A Linux guest is created by Lima; this is distinct from Linux-host support.

Read [the execution guide](experiment/README.md) first. Each invocation uses one disposable ARM64 Ubuntu VM with **4 vCPU, 4 GiB RAM and a 20 GiB sparse disk**. Reserve RAM headroom beyond the guest and at least 30 GiB free host disk. The measured host had 32 GiB RAM. Approximately 1.98 GB of pinned VM assets plus guest packages are downloaded. One measured session took roughly 13-15 minutes; availability and runtime are not guaranteed. The host needs Python 3.12+, Internet and working Apple virtualization; host Docker, Rosetta and a preinstalled Lima are not required.

After a separate explicit decision to authorize the documented guest-root/Docker/network operations, run **one session at a time**:

```sh
python3 experiment/run_session.py --stage calibration --output "$PWD/new-results/session-01"
python3 scripts/verify_session.py "$PWD/new-results/session-01" --json "$PWD/new-results/session-01-verification.json"
```

The existing `calibration` stage runs health qualification **and the full original scheduling pilot**. Its name does not mean calibration-only. Do not use `full` or `timing` with this payload. Never reuse an output directory, retry a consumed session until green, or append a new session to the closed three-run cohort.

Expected outputs include a guest archive, its recorded SHA-256, copied input sources, host summary, scoped VM ledger and local host logs. Keep them together, including failed/partial attempts. [Fresh-output verification](docs/VERIFYING_A_SESSION.md) checks application records, original numerical network bounds, export integrity, package/resource records and **recorded** cleanup separately. Its PASS is bounded file validation, not independent live teardown, a new replication claim or final scientific performance eligibility. It does not require historical latency values or the same number of deadline misses.

**No new VM has been executed to validate this public packaging.** The complete path has been inspected and checked offline; a separately authorized clean-room VM run remains outstanding. If export or cleanup fails, preserve all available files and stop before another session.

## Provenance and licensing

The 34 [published runtime/support inputs](experiment/INPUTS.sha256.json) are unchanged bytes from the original common 38-file capture. Four non-runtime historical/context files are intentionally omitted. The original host lifecycle runner is also unchanged. [Source identities](experiment/SOURCE.json) retain measured revision `b47689f644397018d408e97f83be5c587d7182ff` and audited results revision `33035e085988ce2165fdd46755ee8f75cb3a04e4`; packaging changes do not retroactively change acquisition provenance. [MANIFEST.sha256](MANIFEST.sha256) covers this public snapshot.

[Wang et al. (2026)](https://doi.org/10.1109/ICDCSW72724.2026.00054) informs comparison methodology; this CPU-task pilot does not reproduce its multi-mode AI benchmark. See [the reproducibility audit](docs/REPRODUCIBILITY_AUDIT.md) for scope, checks and remaining limits. **No general reuse license has yet been granted for the original code, report or data**; see [licensing and upstream attribution notes](docs/LICENSING.md).
