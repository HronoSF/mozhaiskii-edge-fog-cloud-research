# Scheduling model of the recorded experiment

This document describes the acquisition implementation, without changing it. The research note gives a compact policy comparison; the equations and edge cases below specify how the published code computes its estimates. All durations and timestamps are integer nanoseconds in the checked guest monotonic-clock domain. Predictions are estimates, not simulated execution or measurements of future completion.

## Source and decision inputs

The relevant versioned sources are:

- [`core.py`](../experiment/tests/scheduling/madt_scheduling/core.py): `eligible`, `predict`, `choose`, and the causal `Ledger`.
- [`guest_pilot.py`](../experiment/tests/scheduling/guest_pilot.py): `freeze_profiles`.
- [`orchestrator.py`](../experiment/tests/scheduling/madt_scheduling/orchestrator.py): snapshot capture, timed placement, sender queues and result validation.
- [`worker.py`](../experiment/tests/scheduling/madt_scheduling/worker.py): input admission, the execution FIFO, result return and telemetry.

For each decision, the orchestrator freezes the candidate task, profiles and worker views. A view contains assigned tasks in assignment order, their latest known phases and timestamps, the active sender upload, online status, unresolved credits and reserved bytes. The predictor uses this snapshot and decision time $t$. It has no access to future task outcomes or unreceived worker observations.

## Eligibility and policy choice

A worker is eligible when it is online, has fewer than 32 unresolved assignments, and can reserve the candidate's input size plus 1 MiB without exceeding 64 MiB. These application reservations are separate from the container memory limit. A busy execution slot remains eligible. If no worker is eligible, dispatch waits for a state change; a task whose reservation exceeds the entire limit is rejected.

Round Robin starts at E and advances cyclically through E, F and C, skipping ineligible workers. It does not use calibration profiles. Compute-ECT and Network-ECT evaluate each eligible worker and choose the smallest predicted response-completion timestamp. Adding or removing the common decision time does not change this choice. Equal scores use the stable E/F/C order.

## Frozen calibration profiles

For worker $j$ and task class $k$, $s_j(k)$ is execution wall time, estimated from three unshaped calibration samples. A task class includes both iteration count and input size. For worker $j$ and input size $b$, transport estimates are:

| Estimate | Recorded interval | Interpretation |
|---|---|---|
| $u_j(b)$ | $f-e$ | Sender start to complete input admission at the worker |
| $a_j(b)$ | $\text{ack receipt}-f$ | Admission to acknowledgement receipt at the orchestrator |
| $v_j(b)$ | $z-y$ | Execution finish to verified result receipt |

Transport uses six samples per worker/input size in each network condition, pooling the two work classes. Every estimate is the ceiling-rounded arithmetic mean, implemented as `(sum(values) + len(values) - 1) // len(values)`. Service profiles are shared across conditions; transport profiles are condition-specific. Profiles are fixed before the scored comparisons and are shared across policies. No scored outcome updates them.

## Residual execution estimate

If the snapshot reports a task executing since $x$, its residual is

$$
R_j(t)=\max\{0,\ s_j(k_{\rm run})-(t-x)\}.
$$

It is zero if no task is reported executing. The code rejects multiple reported running tasks or an invalid running timestamp. If actual execution outlasts its profile, the residual becomes zero: the predictor does not extrapolate additional runtime. This can underestimate waiting time. It does **not** finish the actual task, remove it from the ledger, release capacity or permit concurrent execution. Only a validated result releases its credit and reservation.

## Compute-ECT

Let $W_j$ contain assigned tasks still awaiting input delivery or execution, in assignment order. Tasks reported executing, returning a result or completed are excluded. Candidate $i$ is scored as

$$
\widehat F^{\rm C}_j(i)=t+R_j(t)+\sum_{k\in W_j}s_j(k)+s_j(i).
$$

This is `predict(..., network=False)`: it runs the same queue traversal as Network-ECT with input, acknowledgement and result-return estimates set to zero. It deliberately isolates compute and queue accounting from transport prediction. Actual transfers, sender serialization and result return still occur and remain included in measured response time. The policy is not an assertion that transport is negligible or an optimal scheduler for the emulated topology.

## Network-ECT

Maintain two independent predicted availability times: execution $C_j$ and upload $U_j$. Initialize

$$
C_j=t+R_j(t),\qquad U_j=t.
$$

If an upload began at $e$ and its admission acknowledgement is still outstanding, replace the upload initialization by

$$
U_j=\max\{t,\ e+u_j(b)+a_j(b)\}.
$$

This retains sender occupancy even if the task has already started execution, is returning its result, or completed before its admission acknowledgement arrived. A completed-before-ACK entry remains available to the predictor for this purpose. An active-upload ID without its ledger entry and send timestamp is rejected.

Traverse the pending assignments in assignment order, followed by the candidate. Skip tasks reported executing, returning or completed: their CPU work is already represented by the residual or is finished. For each remaining task $k$, choose the **first applicable** readiness case:

| Priority | Controller-known state | Predicted input readiness $A_{jk}$ |
|---|---|---|
| 1 | Already in the worker FIFO (`worker_wait`) | $t$ |
| 2 | The active upload, with sender start $e_k$ | $\max\{t,e_k+u_j(b_k)\}$ |
| 3 | Upload not yet started | $U_j+u_j(b_k)$ |

Priority matters. A task already known to be in the worker FIFO is ready at $t$ even if its sender acknowledgement remains outstanding. Only case 3 advances $U_j$ to $A_{jk}+a_j(b_k)$; the active upload was accounted for at initialization.

After each remaining task, update

$$
C_j\leftarrow\max\{C_j,A_{jk}\}+s_j(k).
$$

After the candidate has been appended, its score is

$$
\widehat F^{\rm N}_j(i)=C_j+v_j(b_i).
$$

The separate availability times allow input transfer of the next task to overlap current computation. The maximum prevents its execution before both its input and CPU slot are ready. An admission acknowledgement holds the sender slot, not the execution slot. Result return extends the candidate's response estimate but does not hold its CPU slot. Therefore a single sum of all transport and compute durations would not describe the implementation.

## Controller knowledge and stale observations

Workers emit state reports on a nominal 100 ms schedule. The ledger also learns from admission acknowledgements and validated result messages; telemetry is not its only information source. It accepts newer report sequence numbers, checks causal timestamps and preserves phase progress when an older phase arrives through another channel. It retains local assignments and does not interpret omission from a report as verified completion.

Prediction uses the latest accepted, controller-known state. Delayed observations can leave the controller treating physically finished work as waiting or executing, while an exhausted residual can underestimate an overrun. Fixed profiles can also be inaccurate under different contention or transport conditions. These are model limitations and possible questions for a controlled follow-up. The three recorded sessions did not isolate telemetry age, update frequency or prediction error as experimental factors, and establish no measured stale-telemetry defect.

## Scope of verification

The equations above are a description of `predict`, not a new scheduling algorithm or a proof of prediction accuracy. Offline contract tests cover causal accounting, capacity and representative queue/transport cases. The recorded VM executions validate actual task results and execution constraints separately. Neither passing those tests nor editing this description constitutes a new VM experiment.
