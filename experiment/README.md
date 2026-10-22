# Run the original application pilot

This directory publishes the 34-file runtime/support subset of the common 38-file A01-A03 input capture. `run_session.py` is the original owned Lima lifecycle runner, unchanged apart from its public filename. `INPUTS.sha256.json` pins every payload file. Some captured support files are not standalone entrypoints; use the command below. The historical plan and unused host-study wrappers were omitted; no guest runtime imports them. Complete original captures are retained separately. No historical data, live approvals or internal reviews are execution inputs.

## Requirements and effects

The measured host was an Apple Silicon Mac with32 GiB RAM. The runner supports macOS ARM64 with Apple's Virtualization.framework. Each invocation creates **one fresh Lima 2.2.1 ARM64 VM with4 vCPU,4 GiB RAM and a 20 GiB sparse disk**, without host mounts, forwarded SSH agents, Rosetta or guest port forwarding. Allow at least30 GiB free host disk and RAM headroom for the guest. About 1.98 GB of pinned Lima/Ubuntu assets plus guest packages are downloaded per fresh session; measured wrapper durations were roughly 13-15 minutes, not a promised runtime.

The guest installs pinned Docker 28.5.2/containerd 1.7.29, Python dependencies and MADT revision `ca7df8460448ae515f17bfb3a594b30ef9503415`. It uses guest root operations, Docker and `tc/netem` routing/delay/rate/cut/recovery operations. **Run only after explicitly deciding to create this disposable VM. Do not execute bootstrap or proof scripts directly on your Mac, shared Linux host or an existing Docker server.** No host Docker configuration is required or changed by the runner.

The pinned base VM is Ubuntu 24.04 ARM64 release 20260926, SHA256 `1d6bffe64b848468ac97f821d369a4846d983de1800ccf6b5ec8853e85cefc55`. Lima archive SHA256 is `9e9eacce88f37e185c346bad73aa6136f738d8cdf8c3bb23cd42b071824bc66e`. Package locks and full expected manifests are under `tests/runtime-baseline/`. Provisioning refuses a mismatched baseline rather than substituting newer versions. Upstream package availability is an unresolved future operational risk; this is not an offline package mirror.

## Offline checks first

From the repository root:

```sh
python3 scripts/verify_release.py
PYTHONPATH=experiment/tests/scheduling python3 -m unittest discover -s experiment/tests/scheduling/madt_scheduling/tests -p 'test_*.py'
python3 experiment/run_session.py --help
```

Those commands do not start a VM. They do not establish experimental success.

## One new disposable VM session

From the repository root, after checking resources and deciding to authorize the guest operations:

```sh
python3 experiment/run_session.py --stage calibration --output "$PWD/new-results/session-01"
```

`--stage calibration` is required here: the captured application wrapper uses this stage to run health qualification followed by the **full original scheduling pilot**, not just calibration. Do not use the runner's historical `full` or `timing` stages with this application payload. The output directory must not already exist. Do not launch multiple copies concurrently.

The sequence is:

1. Download and hash-check Lima and the Ubuntu image; create the fresh owned VM.
2. Install/check pinned guest and endpoint dependencies.
3. Preserve the original unpatched expected-failure network control, apply the pinned tcconfig compatibility patch, run mapping checks and network qualification.
4. Run 72 calibration tasks,12 queue-proof tasks,720 warmup executions and144 scored tasks in the original 12 cells. G/E/F/C CPU limits are 0.50/0.25/0.50/1.00; each container has 256 MiB; workers have one slot and explicit FIFO queues.
5. Attempt the one-shot evidence export, then stop/delete only the owned VM. Export/bootstrap/timeouts can fail; inspect every resulting record.

The underlying application adapter records functional correctness separately from the original network thresholds. A numerically OUT_OF_SPEC network treatment is not strictly comparable performance evidence. No criterion or workload should be changed after inspecting outcomes.

## Preserve and interpret all outcomes

Inspect `host-summary.json`, `vm-ledger.json`, `input-sha256.json` and `guest-evidence.tar.gz`. Verify the exported hash recorded by the runner, and inspect guest `scheduling/state.json`, its per-cell summaries/tasks, network measurements and resource readbacks. A wrapper exit 0 alone is not an independent scientific audit or proof that every original numerical condition passed. The public CSVs are an audited export of A01-A03; fresh outputs require their own complete validation before publication.

The guest's original container cleanup is scoped by resource identity; the host supervisor records its owned VM teardown. If `cleanup_requires_attention` is present, preserve the work directory/ledger and inspect it before any further run. Never use a broad Docker/VM prune. If one-shot export fails, retain all available host/partial evidence and stop pending investigation. Do not rerun the same output slot until green or relabel a replacement as the failed session.

For a new repeatability study, prospectively specify fresh session identifiers, repetitions, failure/stopping rules, exact source/dependencies and approval before collecting. A01-A03 is a closed cohort; a future invocation is new evidence and must not be appended to it. No new experiment was performed to test this public packaging.
