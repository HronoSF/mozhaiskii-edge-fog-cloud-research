# Issue #13: prospective correctness pilot, not the formal comparison

Status: historical prospective plan captured before execution. Both approved guests
have now run; outcomes and exact captured input revisions are in
`reports/MADT_SCHEDULING_PILOT.md`. This file does not authorize another guest.
Base main:76318b4b9cbbedad9204c0d16e26dae4ae0428e4. User's current task overrides
older two-policy wording in issue13: RR, Compute-ECT and Network-ECT are required.
The model and methodology remain those in merged PR14/15. No new simulator,
Kubernetes or dependency/network repair is included.

## Application/protocol contract

Three independent channels per worker role: one ordered upload socket, a reverse
event socket (results +100ms telemetry), and independent CPU execution. Admission
ACK means complete validated input entered the FIFO, never completed service.
An asyncio event loop handles transport; one thread performs the actual SHA256 /
PBKDF2 kernel and records thread CPU time and monotonic x/y. Results enter a
bounded output queue without making CPU execution wait for result delivery.
There is one nonpreemptive CPU slot, at most32 unresolved reservations and64MiB
reserved per worker. Worker memory is256MiB. Gateway/worker allocations follow
the proposal (G/E/F/C=.5/.25/.5/1CPU,100ms period); fog still routes traffic.

Length-prefixed bounded JSON control frames carry run ID, worker ID, task ID,
per-worker commitment sequence and payload SHA256; uploads carry raw fixed-size
binary data, results encode exactly256 application bytes as base64 inside the
control frame. Base64/framing is protocol overhead, not a claim of256wire bytes.
Inputs/results are prepared at the source before timed releases. Consequently
source memory is bounded here by the tiny task/60-warmup cap, not a claim of
support for the formal4096-task trace under the same memory limit.

Result confirmations also piggyback on upload headers. This prevents a new
commitment from racing ahead of the previous result ACK on a separate TCP path
and falsely exceeding the worker's unconfirmed-phase limit. Confirmation is a
positive source validation, never an estimate of completion. Worker epoch and
report sequence guard restarts/reordering; phase merging is monotone by ID.
Policies receive frozen tuple/dataclass snapshots, not evaluator result or future
trace tables. Compute-ECT zeros initialized and subsequent communication estimates
only in prediction; actual transport is unchanged. Credits stay held on bad or
missing results until explicit shutdown. Fixed drain expiration produces recorded
unresolved outcomes, not a successful completion or automatic score exclusion.

## Predeclared guest scope

Explicitly approved by the user on2026-10-19: two disposable native-ARM64 Linux VMs, sequentially. Initially assigned one to
the author and one to the reviewer; after author attempt01 failed at application
preflight, the user clarified that the author must deliver the pilot and the
reviewer must verify it. The author therefore owns guest02 within the same
approved total; no third VM or independent guest reproduction is implied. Each uses the existing pinned Lima /
Ubuntu assets, Docker28.5.2, bounded tcconfig patch and MADT source. No host Docker,
network/sysctl/virtualization settings, broad cleanup or persistent installation.
No retry selected by observed traffic/policy outcome. All startup/setup failures
are retained. Any further data-bearing VM attempt needs a new stated reason/scope.

1. Run the existing unchanged `guest_repair_proof.sh calibration`: unpatched
   failure control, patch/regressions/mapping, calibration and cut/recovery. A
   failed calibration stops this guest's application pilot. No threshold change.
2. Start a fresh original four-container MADT topology with the gateway/worker
   role mapping. Reuse the existing network harness without editing MADT/tcconfig.
   Verify actual resources, G->C via F, G->E unaffected route, exact qdisc readback,
   counters and a source-path cut/restoration before scored applications.
3. Development calibration:36 isolated jobs per network condition (3per each of
   four classes on each of3workers), unshaped and cloud-ingress delay20ms. Retain
   all samples. Freeze service estimates from unshaped samples and size-specific
   input/ACK/result profiles separately per condition, using integer-ceiling
   arithmetic means. No evaluation-outcome refitting.
4. One forced queue proof:4 heavy large-input requests per worker, released
   together, no artificial sleeps. Verify at least one full input arrives while
   that worker is actually executing a predecessor, and execution intervals never
   overlap on a worker. Publish all per-worker cases, including an absent queue
   if the chosen load fails to expose it. It cannot be relabeled a scheduler win.
5. Twelve tiny comparison cells:3policies x2arrival shapes x2static conditions,
   one VM-session block. Each has N12,H6s,seed0 and the same balanced class/ID/
   payload sequence. Scale the reviewed steady/burst time formulas with H6s;
   these are development traces, not the reviewed formal120s offered-load study.
   Every comparison runs the same ordered60-job warmup, then emptiness barrier,
   then open-loop releases and at most60s drain. Reset processes, queues,
   reservations and connections per cell. Hash/order all cells before results;
   hash key `ehu-pilot-order-v1|policy|scenario|network`, lexicographic ties.
   Fixed tie order E,F,C. Capture cgroup/route/qdisc/counters before and after.

The reduced3-sample profiles, N12/H6s and one session are explicit pilot deviations
from the proposed30-sample profiles,120s traces and10-block formal study. They
serve wiring/correctness/calibration, not hypothesis testing, fine timing accuracy
or performance ranking. No180-run matrix, rate10 comparison cells, tuning after
outcomes, bootstrap confidence intervals, statistical significance or publication
claim. Existing health check retains its original separate rate10 treatment.

## Clock, outcome and validity gates

Require matching Linux boot ID, time-namespace inode, and zero time offsets in
all four endpoints; also15 causal timestamp probes before warmup. All successful
jobs must satisfy a<=g<=b<=c<=d<=e<=f<=x<=y<=z and exact additive telescope; a* is
separate. D_wall/D_thread_cpu and worker execution CPU are distinct. Include
release lag, bad/rejected/unreleased/censored jobs in all-offered accounting. Do
not infer all-offered tails from only completed jobs or add decision cost twice.

Raw worker admissions/execution events are independent of the source's received
telemetry and are used only after the run to check FIFO, overlap and slot cap.
An instrument violation or failed unchanged network qualification stops the
remaining pilot cells; preserve planned cells as not executed, never replace them
with a chosen successful repeat. A correct deadline miss is a result. An absent
local queue is a failed queue demonstration, not permission to inflate service
work after seeing data. Issue12 cross-session repeatability remains unresolved;
this pilot cannot close it. No new infrastructure repair follows instability.

## Local checks and evidence policy

Offline analytical/state tests need no root or sockets. Localhost checks use
separate real Python processes and unprivileged127.0.0.1ports, synthetic declared
profiles, no quotas and no MADT. Never treat them as packet-emulation evidence.
New local runs freeze application source bytes before starting processes. The
initial development socket-denied attempt01 produced no task data; unpinned
preliminary attempt02 produced task records before input-freezing support was
added. Retain both with this limitation. Two newly added global-queue tests
found missing mutation notifications (unit03 failed); fix and retain the failure.

Raw attempts are immutable/new paths. Commit modest manifests/analysis and a
compressed verifiable raw bundle rather than duplicated dependency trees or
huge logs. Preserve exact input hashes, commands, process exits and cleanup. A
fresh independent session must review final cumulative code/tests/evidence SHA;
author checks alone do not approve the instrument. User decides merge.
