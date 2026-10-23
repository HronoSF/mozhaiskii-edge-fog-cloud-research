# Verify one newly collected session offline

Use Python 3.12+ from the repository root. No Docker, Lima, network, root permission or private research files are needed. The verifier reads files without extracting the guest tar or executing any captured code.

```sh
python3 scripts/verify_session.py new-results/session-01 --json new-results/session-01-verification.json
```

Pass the complete runner output directory, not only `guest-evidence.tar.gz`. The JSON destination must be new; it is never overwritten. Preserve the original output, its logs and the verification JSON together. Locally generated VM evidence may contain host identifiers: do not commit it to this public repository without a separate privacy review.

## Status and exit codes

- PASS / exit 0: all implemented public file checks passed. It is not a claim of an independently reproduced VM experiment.
- FAIL / exit 1: at least one implemented check found contradictory, corrupt or explicitly failed evidence.
- UNVERIFIED / exit 2: no definite failure was established, but required evidence is missing. It must never be treated as a pass.

Each domain has its own status. Scientific performance eligibility is a separate field: it remains UNVERIFIED after all public checks pass, and becomes FAIL if a required public check fails. Missing or uncertain cleanup/export can never produce final eligibility. A FAIL in network fidelity does not erase a separately successful application check. Exact latency values and the number of deadline misses may differ from the published cohort without violating application correctness.

## What is checked

| Domain | Evidence and checks |
|---|---|
| Source provenance | Local pinned runtime contracts; captured source manifest and every input file. Accepts exactly the published 34-file subset, or the documented original 38-file capture with its four known context-file hashes. Never imports captured files. |
| Export integrity | Recorded archive SHA-256; complete gzip CRC; tar member safety, duplicates and size limits. A hash from the same output is an integrity check, not an authenticity signature. |
| Application | Frozen plan; two 36-task calibration cells, 12-task queue proof and 12 comparison cells; frozen profile derivation; all 948 source outputs including warmup; unique IDs/completions; per-worker FIFO/non-overlap; process exits, explicit error/shutdown reconciliation, clock hello/probe identities; source/worker/result timestamp agreement; deterministic payload and PBKDF2 reference answers. Original planned-arrival 1 s deadline and all 144 offered comparison outcomes are recomputed. |
| Network fidelity | Health and application qualifications separately; original ordered sample sets, delivery, raw-sample RTT medians, iperf rates, positive path counters and original recorded acceptance checks, terminal health status, original CLI exit (0 for pass, 1 for supported numerical failure), and matching gate/completion receipts at their original acquisition checkpoints. Recomputes 15-25 ms increments, 2 ms restoration/control bounds, 7-11 Mbps limited rate, baseline/restored minimum 20 Mbps and restoration at least 75% of baseline. No threshold changes. |
| Environment | Exact saved guest/endpoint package manifests and original CPU/memory readbacks for G/E/F/C, before and after all comparison cells. |
| Recorded cleanup | Host/standalone VM-ledger equality, deleted-state/identity/absence/port assertions, wrapper cleanup errors and guest container/network inventory restoration. Does not probe the present host or attest that historical ledger claims are true. |
| Wrapper completion | Original stage and recorded guest/supervisor exit status. Wrapper exit zero alone is insufficient. |

The JSON records per-cell offered/completed/on-time counts when application checks complete, and separate health/application fidelity results. An incomplete/corrupt cell cannot receive application PASS. The checker reports the first blocking defect within each domain while continuing other domains where readable evidence allows; it is not an exhaustive forensic inventory of every downstream missing file.

Limits are 256 MiB for archive bytes/expanded gzip data, 32 MiB per member and 10,000 tar members. Links, special files, absolute/traversal paths, duplicate members/JSON keys and non-finite JSON constants are rejected. The historical exports are approximately 13 MiB expanded. Larger future experiments need a separately reviewed verifier scope; do not weaken these limits ad hoc.

## What this command cannot certify

The original independent scientific audit additionally reconciled full route/interface/qdisc snapshots, acquisition environment/provenance, live scoped teardown and preservation seals, approvals and source-bound execution. Not all of that private study tooling and authority evidence is published here. This checker does not replay every causal scheduler decision or fully audit every raw network command/snapshot. Non-numerical network checks are retained recorded predicates, not an independent verification of all underlying commands.

The host runner is not captured inside its output; its exact release hash is checked by `verify_release.py`, but cannot be established from an output directory alone. Saved common-clock/cleanup claims are consistency checks, not external attestations. A prospective study still needs a frozen protocol, all attempted sessions, independently reviewed evidence and observation of actual cleanup before final performance publication. No packet, task or cycle is an independent VM replication.

A clean-room run using only this public package has not been performed. Successful offline tests/builds do not fill that gap.

## Tests are synthetic

```sh
python3 -m unittest discover -s tests -v
```

The fixture generator invents schema-valid clocks, events, network samples and completion records; it uses the frozen deterministic task kernel for reference bytes. These files are tests, never acquisition evidence. Negative tests remove/corrupt records, calibration, cycles, exports and cleanup; change profiles/deadline flags/worker identities; introduce dependency/resource drift and unsafe archives. A separate case permits a different latency/miss count. None starts a VM or opens a network connection.
