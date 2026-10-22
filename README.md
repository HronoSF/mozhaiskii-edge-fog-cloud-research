# Edge-Fog-Cloud Scheduling Research

**Gleb Mozhaiskii**  
Preliminary independent research related to planned doctoral studies at the University of the Basque Country (UPV/EHU). This is a personal research project, not an official university publication.

## The problem

When a computing task arrives, an **orchestrator** decides which worker should execute it. The decision can depend on processing power, tasks already waiting in queues, and network transfer time.

- **Edge** - a computing node close to the request source.
- **Fog** - an intermediate computing node. In this prototype, Fog also routes traffic.
- **Cloud** - a more distant node with a higher assigned CPU quota.

I implemented a real-task experimental baseline with one Gateway and three workers, running as four Docker containers inside one Linux VM. [MADT](https://github.com/dltcspbu/madt) emulates the network and its directional delay. This is not an experiment on four separate physical machines.

![Experiment network topology](figures/topology.svg)

## What I compared

I ran deterministic PBKDF2-HMAC-SHA256 tasks, which perform repeated cryptographic hashing on the CPU and return a verifiable answer. Three schedulers - Round Robin, Compute-ECT and Network-ECT - were compared with steady/bursty arrivals and without/with nominal +20 ms toward Cloud: **12 scenarios**.

In the single completed VM session, all **144/144 scored results** were correct and **143/144** met a 1-second deadline. Edge, Fog and Cloud received **16, 24 and 104** scored tasks, respectively. Two preceding fresh VM attempts stopped at strict network qualification, so **cross-session application repeatability is not established**.

![Outcomes of all 12 experimental scenarios](figures/scenarios.svg)

![A measured Round Robin task timeline](figures/task-timeline.svg)

## Released experimental data

- **[Scenario results (CSV)](data/scenario-results.csv)** - one row per scenario from the successful VM session.
- **[Scored tasks (CSV)](data/scored-tasks.csv)** - selected timing and placement fields for the 144 completed scored tasks.

This is a **correctness-first research prototype**, not evidence of a generally superior scheduling algorithm, physical multi-site portability, or statistically established reproducibility. A new, prospectively specified repetition study is being prepared. Raw guest/provenance archives and internal experimental workflows are not distributed in this public summary.

## Research context

Wang et al., 'Fair Comparison of Scheduling Algorithms on Heterogeneous Edge Clusters: A Continuous Adaptive Benchmark', IEEE ICDCSW 2026 ([DOI](https://doi.org/10.1109/ICDCSW72724.2026.00054)), motivates careful matched scheduling comparisons. My CPU-task pilot does not reproduce its multi-mode AI benchmark.

No software license is implied by this research-summary release. A runnable software artifact will be licensed separately if published.
