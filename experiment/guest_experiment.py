#!/usr/bin/env python3
"""Real standalone MADT packet experiment, for a disposable Linux guest only.

Requires root in a dedicated guest and an already built/pinned ARM64 endpoint
image. Never uses a remote Docker endpoint, mocks packet behavior, or prunes.
The original runtime is tried first. A one-line obsolete Docker-SDK option may
be removed only after its real failure is captured. All evidence survives errors.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
import difflib
import hashlib
import importlib
import ipaddress
import json
import os
from pathlib import Path
import random
import re
import signal
import statistics
import subprocess
import sys
import threading
import time
import traceback
import types
import uuid

PIN = "ca7df8460448ae515f17bfb3a594b30ef9503415"
LABEL = "org.ehu.madt.run"
PLAN = {
    "version": 1, "repetitions": 10, "ping_count": 20,
    "ping_interval_s": 0.1, "ping_deadline_s": 6,
    "delay_ms": 20, "delay_increment_bounds_ms": [15, 25],
    "control_max_median_change_ms": 2, "restore_max_median_change_ms": 2,
    "rate_mbps": 10, "rate_receive_bounds_mbps": [7, 11],
    "unshaped_min_receive_mbps": 20, "restore_min_rate_fraction": 0.75,
    "iperf_measurement_s": 3, "iperf_omit_s": 1,
    "path_cut_ping_count": 3, "path_cut_deadline_s": 4,
    "path_cut_tcp_timeout_s": 6, "path_cut_tcp_connect_timeout_ms": 2000,
    "tc_delay_json_unit": "seconds (iproute2 netem JSON)",
    "tc_rate_text_unit": "SI bits/second from tc class rate output",
    "claims": "Adapted single-host MADT packet path, not generic upstream or Kubernetes validation",
}


class Evidence:
    def __init__(self, output):
        output.mkdir(parents=True, exist_ok=False)
        self.output, self.lock = output, threading.Lock()
        self.events = (output / "events.jsonl").open("a", buffering=1)

    def event(self, action, **details):
        with self.lock:
            self.events.write(json.dumps({"monotonic_ns": time.monotonic_ns(),
                                         "wall_time_ns": time.time_ns(),
                                         "action": action, **details}, default=str) + "\n")

    def save(self, name, value):
        with self.lock:
            temporary = self.output / (name + ".tmp")
            temporary.write_text(json.dumps(value, indent=2, default=str) + "\n")
            temporary.replace(self.output / name)

    def command(self, argv, *, check=True, timeout=30):
        self.event("host_command_start", argv=argv)
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except BaseException as error:
            self.event("host_command_exception", argv=argv, error=repr(error))
            raise
        self.event("host_command_end", argv=argv, returncode=result.returncode,
                   stdout=result.stdout, stderr=result.stderr)
        if check and result.returncode:
            raise RuntimeError(f"Command failed ({result.returncode}): {argv}")
        return result


class RealSubprocessRecorder:
    """Instrument real upstream shell calls; never substitutes their outputs."""
    PIPE = subprocess.PIPE

    def __init__(self, evidence):
        self.evidence = evidence

    def run(self, *args, **kwargs):
        self.evidence.event("upstream_shell_start", args=args, kwargs=kwargs)
        result = subprocess.run(*args, **kwargs)
        self.evidence.event("upstream_shell_end", args=args, returncode=result.returncode,
                            stdout=result.stdout, stderr=result.stderr)
        return result


class Experiment:
    def __init__(self, args):
        self.args, self.ev = args, Evidence(args.output)
        self.token = "ehu" + uuid.uuid4().hex[:12]
        self.prefix = self.token + "_"
        self.names = {name: self.prefix + name for name in ("edge", "fog", "cloud", "control")}
        self.network_names = {self.prefix + name for name in ("access", "wan")}
        self.ledger = {"token": self.token, "planned_containers": self.names,
                       "planned_networks": sorted(self.network_names),
                       "containers": [], "networks": [], "cleanup_errors": []}
        self.ev.save("ledger.json", self.ledger)
        self.measurements, self.checks = [], []
        self.socket = self.context = None
        self.client = None
        self.collections = None

    def check(self, description, passed, **details):
        row = {"description": description, "passed": bool(passed), **details}
        self.checks.append(row)
        self.ev.event("acceptance_check", **row)
        return passed

    def require(self, description, passed, **details):
        if not self.check(description, passed, **details):
            raise RuntimeError(description)

    def preflight(self):
        self.require("root in Linux guest", sys.platform == "linux" and os.geteuid() == 0)
        self.require("no remote Docker override", not os.getenv("DOCKER_HOST")
                     and not os.getenv("DOCKER_CONTEXT"))
        self.require("MADT exact source pin", self.ev.command(
            ["git", "-C", str(self.args.source), "rev-parse", "HEAD"]).stdout.strip() == PIN)
        self.require("MADT full source tree clean", not self.ev.command(
            ["git", "-C", str(self.args.source), "status", "--porcelain"]).stdout.strip())
        self.ev.command(["uname", "-a"])
        self.ev.command(["cat", "/etc/os-release"])
        self.ev.command(["ip", "-j", "address", "show"])
        self.ev.command(["ip", "-j", "route", "show", "table", "all"])
        for command in (["tc", "-V"], ["tcset", "--version"], ["tcdel", "--version"],
                        ["nsenter", "--version"], ["python3", "--version"]):
            self.ev.command(command)
        self.ev.command([sys.executable, "-m", "pip", "freeze"])
        import docker
        self.client = docker.DockerClient(base_url="unix:///var/run/docker.sock", timeout=15)
        info = self.client.info()
        self.require("ARM64 Docker guest", info.get("Architecture") in ("aarch64", "arm64"))
        self.ev.save("docker-environment.json", {"version": self.client.version(),
                     "info": {k: info.get(k) for k in ("Architecture", "NCPU", "MemTotal",
                          "OperatingSystem", "KernelVersion", "CgroupVersion", "Driver")}})
        image = self.client.images.get(self.args.image)
        self.require("immutable endpoint image ID", self.args.image == image.id)
        self.require("ARM64 endpoint image", image.attrs.get("Architecture") == "arm64")
        self.require("endpoint image declares no implicit volumes", not image.attrs.get("Config", {}).get("Volumes"))
        self.ev.save("endpoint-image.json", {"id": image.id, "attrs": image.attrs})
        existing_containers = self.client.containers.list(all=True)
        existing_networks = self.client.networks.list()
        self.ev.save("docker-inventory-before.json", {
            "containers": [c.id for c in existing_containers],
            "networks": [n.id for n in existing_networks],
        })
        self.require("planned names absent", not ({c.name for c in existing_containers}
                     & set(self.names.values())) and not ({n.name for n in existing_networks}
                     & self.network_names))
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(self.args.source))
        self.runtime = importlib.import_module("madt_lib.runtimes.docker_runtime")
        self.runtime.subprocess = RealSubprocessRecorder(self.ev)

    def instrument_resource_creation(self):
        # Ownership labels/ledger are neutral instrumentation of real SDK calls.
        # No Docker response, socket, route or traffic operation is mocked.
        from docker.models.containers import ContainerCollection
        from docker.models.networks import NetworkCollection
        original_container, original_network = ContainerCollection.create, NetworkCollection.create
        self.collections = (ContainerCollection, NetworkCollection, original_container, original_network)
        experiment = self

        def create_container(collection, *args, **kwargs):
            name = kwargs.get("name")
            if name not in experiment.names.values():
                raise RuntimeError(f"Unexpected container creation: {name}")
            labels = dict(kwargs.get("labels", {}))
            labels[LABEL] = experiment.token
            kwargs["labels"] = labels
            experiment.ev.event("container_create_intent", name=name,
                                image=str(kwargs.get("image")), kwargs_keys=sorted(kwargs))
            container = original_container(collection, *args, **kwargs)
            experiment.ledger["containers"].append({"id": container.id, "name": name})
            experiment.ev.save("ledger.json", experiment.ledger)
            experiment.ev.event("container_created", id=container.id, name=name)
            return container

        def create_network(collection, *args, **kwargs):
            name = kwargs.get("name", args[0] if args else None)
            if name not in experiment.network_names:
                raise RuntimeError(f"Unexpected network creation: {name}")
            labels = dict(kwargs.get("labels", {}))
            labels[LABEL] = experiment.token
            kwargs["labels"] = labels
            experiment.ev.event("network_create_intent", name=name, driver=kwargs.get("driver"))
            network = original_network(collection, *args, **kwargs)
            experiment.ledger["networks"].append({"id": network.id, "name": name})
            experiment.ev.save("ledger.json", experiment.ledger)
            experiment.ev.event("network_created", id=network.id, name=name)
            return network

        ContainerCollection.create, NetworkCollection.create = create_container, create_network

    def make_lab(self, attempt):
        from madt_lib import Network, Node
        workspace = self.ev.output / f"attempt-{attempt}"
        workspace.mkdir()
        lab = workspace / "lab"
        socket_base = workspace / "sockets"
        (socket_base / "lab").mkdir(parents=True)
        os.environ["MADT_LABS_SOCKETS_DIR"] = str(socket_base)
        network = Network("10.123.0.0/16")
        options = dict(image=self.args.image, enable_internet=False,
                       entrypoint="/bin/sleep infinity", labels={LABEL: self.token},
                       mem_limit="256m", nano_cpus=1_000_000_000)
        edge, fog, cloud, control = [network.create_node(n, **options)
                                    for n in ("edge", "fog", "cloud", "control")]
        fog.type = Node.ROUTER
        fog.add_options(sysctls={"net.ipv4.ip_forward": "1"})
        access = network.create_subnet("access", (edge, fog, control))
        wan = network.create_subnet("wan", (fog, cloud))
        network.configure()
        network.render(str(lab))
        config_path = lab / "lab.json"
        config = json.loads(config_path.read_text())
        self.ev.save(f"attempt-{attempt}-lab-original.json", config)
        # A static router needs only its connected routes. MADT's self-default is
        # generated for this manually marked router; remove that one field only.
        original_routes = config["nodes"]["fog"]["routes"]
        self.require("fog routes only point to itself", bool(original_routes)
                     and all(gw in {fog.get_ip(access), fog.get_ip(wan)}
                             for gw in original_routes.values()), routes=original_routes)
        config["nodes"]["fog"]["routes"] = None
        config_path.write_text(json.dumps(config, indent=2) + "\n")
        self.ev.save(f"attempt-{attempt}-lab-adapted.json", config)
        self.ev.event("static_router_adapter", removed_fog_routes=original_routes)
        for name, node in config["nodes"].items():
            for subnet, address in node["networks"].items():
                self.require("model address belongs to referenced subnet",
                             ipaddress.ip_interface(address).ip in ipaddress.ip_network(
                                 config["networks"][subnet]["subnet"]), node=name, subnet=subnet)
        self.addresses = {"edge": edge.get_ip(access), "control": control.get_ip(access),
                          "cloud": cloud.get_ip(wan), "fog_access": fog.get_ip(access),
                          "fog_wan": fog.get_ip(wan)}
        self.ev.save("model-addresses.json", self.addresses)
        self.lab, self.socket_path = lab, socket_base / "lab" / "lab.sock"

    def start(self):
        self.instrument_resource_creation()
        random.seed(20261019)
        for attempt in (1, 2):
            self.make_lab(attempt)
            try:
                with (self.ev.output / f"attempt-{attempt}-runtime.txt").open("w") as log:
                    with redirect_stdout(log), redirect_stderr(log):
                        ids, _ = self.runtime.start_lab(str(self.lab), self.prefix,
                                                       timeout=30, poll_interval=2)
                log_text = (self.ev.output / f"attempt-{attempt}-runtime.txt").read_text()
                self.require("no upstream network setup error", "ERROR WHILE SETTING UP NETWORKING" not in log_text)
                self.require("four real containers returned", len(ids) == 4)
                break
            except BaseException as error:
                self.ev.event("upstream_start_failure", attempt=attempt,
                              exception=repr(error), traceback=traceback.format_exc())
                if attempt != 1 or not isinstance(error, (TypeError,)) or "version" not in str(error):
                    # Docker SDK may wrap unsupported options as InvalidArgument.
                    import docker
                    if attempt != 1 or not isinstance(error, docker.errors.InvalidArgument) or "version" not in str(error):
                        raise
                self.cleanup_resources()
                self.require("clean retry boundary", not self.ledger["cleanup_errors"])
                original_path = self.args.source / "madt_lib/runtimes/docker_runtime.py"
                original = original_path.read_text()
                line = "            'version': dc.api._version,\n"
                self.require("one exact obsolete SDK option", original.count(line) == 1)
                adapted = original.replace(line, "", 1)
                (self.ev.output / "runtime-compatibility.patch").write_text("".join(
                    difflib.unified_diff(original.splitlines(True), adapted.splitlines(True),
                                         fromfile="upstream/docker_runtime.py", tofile="adapted/docker_runtime.py")))
                self.ev.save("runtime-adapter-provenance.json", {
                    "reason": repr(error), "source_sha": PIN,
                    "original_sha256": hashlib.sha256(original.encode()).hexdigest(),
                    "adapted_sha256": hashlib.sha256(adapted.encode()).hexdigest(),
                    "execution": "one-line in-memory module transformation; checkout unchanged"})
                module = types.ModuleType("madt_lib.runtimes.docker_runtime_compat")
                module.__package__, module.__file__ = "madt_lib.runtimes", str(original_path)
                exec(compile(adapted, str(original_path), "exec"), module.__dict__)
                module.subprocess = RealSubprocessRecorder(self.ev)
                self.runtime = module
        import zmq
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PULL)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.bind("ipc://" + str(self.socket_path))
        self.ev.event("actual_headless_zmq_barrier_bound", path=str(self.socket_path))
        self.containers = {n: self.client.containers.get(name) for n, name in self.names.items()}
        self.ev.save("container-inspect.json", {n: c.attrs for n, c in self.containers.items()})
        for n, c in self.containers.items():
            self.require("run-owned running container", c.labels.get(LABEL) == self.token
                         and c.status == "running", node=n)
            self.require("no published application ports", not c.attrs["HostConfig"].get("PortBindings"), node=n)
            self.require("no privileged or host-network container", not c.attrs["HostConfig"].get("Privileged")
                         and c.attrs["HostConfig"].get("NetworkMode") != "host", node=n)
            self.require("only model Docker attachments", set(c.attrs["NetworkSettings"]["Networks"])
                         <= self.network_names, node=n)
            mounts = c.attrs.get("Mounts", [])
            self.require("only the run-owned guest socket bind mount", len(mounts) == 1
                         and mounts[0].get("Type") == "bind" and mounts[0].get("Destination") == "/lab"
                         and Path(mounts[0]["Source"]).resolve() == self.socket_path.parent.resolve(), node=n)
        barrier_probe = """import json,pathlib,time
for attempt in range(40):
    pids = [1] + [int(p) for p in pathlib.Path('/proc/1/task/1/children').read_text().split()]
    for pid in pids:
        try:
            args = pathlib.Path('/proc/%d/cmdline' % pid).read_bytes().split(b'\\0')
        except FileNotFoundError:
            continue
        if args and args[0].endswith(b'sleep') and b'infinity' in args:
            print(json.dumps({'sleep_infinity_pid': pid, 'attempt': attempt}))
            raise SystemExit(0)
    time.sleep(0.2)
raise SystemExit('MADT entrypoint did not leave its socket barrier within 8 seconds')
"""
        for node in self.containers:
            self.exec(node, ["timeout", "10", "python3", "-c", barrier_probe])
        self.exec("cloud", ["iperf3", "-s", "-D"])
        self.exec("edge", ["iperf3", "-s", "-D"])
        self.inventory_interfaces()
        self.verify_routes()

    def exec(self, node, argv, *, check=True):
        self.ev.event("container_command_start", node=node, argv=argv)
        result = self.containers[node].exec_run(argv, demux=True)
        stdout = (result.output[0] or b"").decode(errors="replace")
        stderr = (result.output[1] or b"").decode(errors="replace")
        row = {"node": node, "argv": argv, "exit_code": result.exit_code,
               "stdout": stdout, "stderr": stderr}
        self.ev.event("container_command_end", **row)
        if check and result.exit_code:
            raise RuntimeError(f"Container command failed: {node} {argv}: {stderr} {stdout}")
        return row

    def inventory_interfaces(self):
        self.interfaces = {}
        host_links = json.loads(self.ev.command(["ip", "-j", "link", "show"]).stdout)
        for node in self.containers:
            data = json.loads(self.exec(node, ["ip", "-j", "address", "show"])["stdout"])
            self.interfaces[node] = data
        def find(node, address):
            matches = [r for r in self.interfaces[node]
                       if any(a.get("local") == address for a in r.get("addr_info", []))]
            self.require("unique interface for model address", len(matches) == 1, node=node, address=address)
            return matches[0]["ifname"]
        self.cloud_if = find("cloud", self.addresses["cloud"])
        self.fog_wan_if = find("fog", self.addresses["fog_wan"])
        self.require("single-homed cloud", len([i for i in self.interfaces["cloud"] if i["ifname"] != "lo"]) == 1)
        peer_index = int(self.exec("cloud", ["cat", f"/sys/class/net/{self.cloud_if}/iflink"])["stdout"].strip())
        peers = [r for r in host_links if r["ifindex"] == peer_index]
        self.require("cloud host veth found", len(peers) == 1)
        self.cloud_veth = peers[0]["ifname"]
        self.ev.save("interface-inventory.json", {"containers": self.interfaces,
                     "host_links": host_links, "cloud_interface": self.cloud_if,
                     "cloud_host_veth": self.cloud_veth, "fog_wan_interface": self.fog_wan_if})
        self.require("fog forwarding enabled", self.exec("fog", ["cat", "/proc/sys/net/ipv4/ip_forward"])["stdout"].strip() == "1")

    def verify_routes(self):
        pairs = [("edge", self.addresses["cloud"], self.addresses["fog_access"]),
                 ("cloud", self.addresses["edge"], self.addresses["fog_wan"]),
                 ("edge", self.addresses["control"], None),
                 ("fog", self.addresses["cloud"], None)]
        for node, destination, gateway in pairs:
            routes = json.loads(self.exec(node, ["ip", "-j", "route", "get", destination])["stdout"])
            self.require("route follows model gateway", len(routes) == 1
                         and routes[0].get("gateway") == gateway, node=node,
                         destination=destination, expected_gateway=gateway, routes=routes)

    def snapshot(self, phase):
        snapshot = {"phase": phase, "host_tc": {}, "containers": {}}
        for family in ("qdisc", "class", "filter"):
            result = self.ev.command(["tc", "-j", "-s", family, "show", "dev", self.cloud_veth])
            text = self.ev.command(
                ["tc", "-s", family, "show", "dev", self.cloud_veth]).stdout
            # iproute2 6.1 emits no JSON for an empty class table. Accept only
            # empty class/filter tables confirmed independently by text output.
            if family in ("class", "filter") and not result.stdout.strip():
                self.require("empty tc table confirmed by text", not text.strip(), family=family)
                self.ev.event("empty_tc_table_normalized", family=family, phase=phase)
                table = []
            elif family == "class" and result.stdout.lstrip().startswith("class htb "):
                # iproute2 6.1 ignores -j for populated HTB classes. Preserve
                # text, confirm stable class headers with a separate read, and
                # leave structured data explicitly unavailable (never empty).
                headers = [line for line in result.stdout.splitlines() if line.startswith("class ")]
                text_headers = [line for line in text.splitlines() if line.startswith("class ")]
                self.require("HTB text headers independently confirmed", bool(headers)
                             and headers == text_headers
                             and all(line.startswith("class htb ") for line in headers))
                snapshot["host_tc"]["class_format"] = "text; JSON unsupported by this tc build"
                self.ev.event("tc_class_json_unavailable", phase=phase, raw=result.stdout)
                table = None
            else:
                table = json.loads(result.stdout)
            if table is not None:
                self.require("tc JSON table is an array", isinstance(table, list), family=family)
            snapshot["host_tc"][family] = table
            snapshot["host_tc"][family + "_text"] = text
        snapshot["cloud_host_veth_link"] = json.loads(self.ev.command(
            ["ip", "-j", "-s", "link", "show", "dev", self.cloud_veth]).stdout)
        for name in self.containers:
            snapshot["containers"][name] = {
                "links": json.loads(self.exec(name, ["ip", "-j", "-s", "link", "show"])["stdout"]),
                "routes": json.loads(self.exec(name, ["ip", "-j", "route", "show"])["stdout"]),
                "cpu_stat": self.exec(name, ["cat", "/sys/fs/cgroup/cpu.stat"], check=False),
            }
        snapshot["cloud_netns_qdisc"] = json.loads(self.exec("cloud", ["tc", "-j", "-s", "qdisc", "show"])["stdout"])
        self.ev.save(f"snapshot-{phase}.json", snapshot)
        return snapshot

    def iperf(self, source, destination, *, seconds=None, negative=False):
        argv = ["timeout", str(PLAN["path_cut_tcp_timeout_s"] if negative else 12),
                "iperf3", "-c", destination, "-J", "-t",
                str(seconds or PLAN["iperf_measurement_s"])]
        if negative:
            argv += ["--connect-timeout", str(PLAN["path_cut_tcp_connect_timeout_ms"])]
        else:
            argv += ["-O", str(PLAN["iperf_omit_s"])]
        raw = self.exec(source, argv, check=False)
        try:
            parsed = json.loads(raw["stdout"]) if raw["stdout"].strip() else {}
        except json.JSONDecodeError as error:
            self.ev.event("iperf_invalid_json", raw=raw, error=repr(error))
            raise
        return {"raw": raw, "json": parsed,
                "receive_bytes": parsed.get("end", {}).get("sum_received", {}).get("bytes", 0),
                "receive_mbps": parsed.get("end", {}).get("sum_received", {}).get("bits_per_second", 0) / 1e6}

    @staticmethod
    def packet_counts(link):
        data = link.get("stats64") or link.get("stats")
        if not data:
            raise RuntimeError("Interface JSON has no packet counters")
        return {direction: data[direction]["packets"] for direction in ("rx", "tx")}

    def ping(self, source, destination, count=None, deadline=None):
        argv = ["ping", "-n", "-c", str(count or PLAN["ping_count"]), "-i",
                str(PLAN["ping_interval_s"]), "-W", "1", "-w",
                str(deadline or PLAN["ping_deadline_s"]), destination]
        row = self.exec(source, argv, check=False)
        rtts = [float(x) for x in re.findall(r"time=([0-9.]+)\s*ms", row["stdout"])]
        totals = re.search(r"(\d+) packets transmitted, (\d+) received", row["stdout"])
        return {"source": source, "destination": destination, "exit_code": row["exit_code"],
                "transmitted": int(totals[1]) if totals else None,
                "received": int(totals[2]) if totals else None,
                "rtt_ms": rtts, "median_ms": statistics.median(rtts) if rtts else None}

    def phase(self, name, throughput=False):
        self.verify_routes()
        before = self.snapshot(name + "-before")
        pairs = [("edge", self.addresses["cloud"]), ("cloud", self.addresses["edge"]),
                 ("edge", self.addresses["control"])]
        with ThreadPoolExecutor(max_workers=3) as pool:
            pings = list(pool.map(lambda p: self.ping(*p), pairs))
        row = {"phase": name, "pings": pings}
        for result in pings:
            self.check("all requested nominal packets received", result["exit_code"] == 0
                       and result["received"] == PLAN["ping_count"], phase=name, ping=result)
        if throughput:
            transfer = self.iperf("edge", self.addresses["cloud"])
            row["iperf"] = transfer
            row["receive_mbps"] = transfer["receive_mbps"]
            self.check("iperf completes", transfer["raw"]["exit_code"] == 0
                       and "error" not in transfer["json"], phase=name)
        after = self.snapshot(name + "-after")
        for interface, old_link, new_link in [
            ("cloud_host_veth", before["cloud_host_veth_link"][0], after["cloud_host_veth_link"][0]),
            ("fog_wan", next(i for i in before["containers"]["fog"]["links"] if i["ifname"] == self.fog_wan_if),
             next(i for i in after["containers"]["fog"]["links"] if i["ifname"] == self.fog_wan_if)),
        ]:
            old, new = self.packet_counts(old_link), self.packet_counts(new_link)
            delta = {direction: new[direction]-old[direction] for direction in old}
            self.require("intended path carries packets in both directions", all(v > 0 for v in delta.values()),
                         phase=name, interface=interface, packet_delta=delta)
            row.setdefault("path_packet_deltas", {})[interface] = delta
        self.measurements.append(row)
        self.ev.save("measurements.json", self.measurements)
        self.ev.event("phase_complete", phase=name, result=row)
        return row

    def shape(self, kind):
        options = {"delay": PLAN["delay_ms"], "delay_unit": "msec"} if kind == "delay" else {
            "rate": PLAN["rate_mbps"], "rate_unit": "Mbps"}
        self.ev.event("impairment_requested", kind=kind, options=options)
        code = self.runtime.tcset_api(self.containers["cloud"].short_id, options)
        self.require("original MADT tc helper succeeds", code == 0, result=code, options=options)
        state = self.snapshot("rule-" + kind + "-" + str(len(self.measurements)))
        kinds = {q.get("kind") for q in state["host_tc"]["qdisc"]}
        self.require("expected shaping qdisc readback", ("netem" in kinds) if kind == "delay"
                     else bool(kinds & {"htb", "tbf"}), kind=kind, qdiscs=state["host_tc"])
        if kind == "delay":
            delays_s = []
            for qdisc in state["host_tc"]["qdisc"]:
                if qdisc.get("kind") == "netem":
                    delay = qdisc.get("options", {}).get("delay")
                    if isinstance(delay, dict):
                        delay = delay.get("delay")
                    if isinstance(delay, (float, int)):
                        delays_s.append(delay)
            self.require("numerical netem delay readback in seconds", len(delays_s) == 1
                         and abs(delays_s[0] - PLAN["delay_ms"]/1000) < 1e-6, delay_seconds=delays_s)
        else:
            rates = [float(number) * {"": 1, "K": 1e3, "M": 1e6, "G": 1e9}[unit]
                     for number, unit in re.findall(r"\brate\s+([0-9.]+)([KMG]?)(?:bit|bps)\b",
                                                   state["host_tc"]["class_text"])]
            self.require("numerical HTB rate readback", any(abs(rate - PLAN["rate_mbps"]*1e6) <= 1
                         for rate in rates), rates_bits_per_second=rates)
        self.ev.event("impairment_applied_and_read_back", kind=kind)

    def restore(self):
        self.ev.command(["tcdel", "--all", "--docker", self.containers["cloud"].short_id])
        result = json.loads(self.ev.command(["tc", "-j", "qdisc", "show", "dev", self.cloud_veth]).stdout)
        self.require("shaping removed", not ({q.get("kind") for q in result} & {"netem", "htb", "tbf"}), qdiscs=result)

    def compare_cycle(self, kind, baseline, impaired, restored):
        for index in (0, 1):
            a, b, c = [r["pings"][index]["median_ms"] for r in (baseline, impaired, restored)]
            if None in (a, b, c):
                self.check("complete RTT sample sets", False, kind=kind, values=[a, b, c])
                continue
            self.check("RTT restoration within frozen tolerance", abs(c-a) <= PLAN["restore_max_median_change_ms"],
                       kind=kind, baseline_ms=a, restored_ms=c)
            if kind == "delay":
                lower, upper = PLAN["delay_increment_bounds_ms"]
                self.check("delay RTT increment within frozen bounds", lower <= b-a <= upper,
                           direction=index, increment_ms=b-a, bounds_ms=[lower, upper])
        control = [r["pings"][2]["median_ms"] for r in (baseline, impaired, restored)]
        self.check("access-segment control unaffected", all(x is not None for x in control)
                   and max(control)-min(control) <= PLAN["control_max_median_change_ms"], values_ms=control)
        if kind == "rate":
            a, b, c = [r["receive_mbps"] for r in (baseline, impaired, restored)]
            lower, upper = PLAN["rate_receive_bounds_mbps"]
            self.check("baseline above requested cap", a >= PLAN["unshaped_min_receive_mbps"], mbps=a)
            self.check("rate-only throughput within frozen bounds", lower <= b <= upper, mbps=b)
            self.check("throughput restores", c >= PLAN["unshaped_min_receive_mbps"]
                       and c >= a * PLAN["restore_min_rate_fraction"], baseline_mbps=a, restored_mbps=c)

    def cycles(self, prefix, repetitions):
        for kind in ("delay", "rate"):
            for index in range(repetitions):
                stem = f"{prefix}-{kind}-{index:02d}"
                baseline = self.phase(stem + "-baseline", throughput=kind == "rate")
                self.shape(kind)
                try:
                    impaired = self.phase(stem + "-impaired", throughput=kind == "rate")
                finally:
                    self.restore()
                restored = self.phase(stem + "-restored", throughput=kind == "rate")
                self.compare_cycle(kind, baseline, impaired, restored)

    def negative_control(self):
        # Establish working TCP in both directions before cutting, so an absent
        # listener cannot manufacture a successful negative-control result.
        pre_tcp = {"forward": self.iperf("edge", self.addresses["cloud"], seconds=1),
                   "reverse": self.iperf("cloud", self.addresses["edge"], seconds=1)}
        self.require("TCP works in both directions before cut", all(t["raw"]["exit_code"] == 0
                     and t["receive_bytes"] > 0 for t in pre_tcp.values()), transfers=pre_tcp)
        self.ev.event("path_cut_requested", node="fog", interface=self.fog_wan_if)
        self.exec("fog", ["ip", "link", "set", "dev", self.fog_wan_if, "down"])
        try:
            self.snapshot("path-cut")
            cloud = self.ping("edge", self.addresses["cloud"], PLAN["path_cut_ping_count"], PLAN["path_cut_deadline_s"])
            reverse = self.ping("cloud", self.addresses["edge"], PLAN["path_cut_ping_count"], PLAN["path_cut_deadline_s"])
            control = self.ping("edge", self.addresses["control"])
            tcp = {"forward": self.iperf("edge", self.addresses["cloud"], seconds=1, negative=True),
                   "reverse": self.iperf("cloud", self.addresses["edge"], seconds=1, negative=True)}
            self.require("cut path fails in both directions", cloud["exit_code"] != 0
                         and cloud["received"] == 0 and reverse["exit_code"] != 0
                         and reverse["received"] == 0, cloud=cloud, reverse=reverse)
            self.require("path cut leaves control reachable", control["received"] == PLAN["ping_count"]
                         and control["exit_code"] == 0, control=control)
            self.require("cut path blocks real TCP without received data", all(t["raw"]["exit_code"] != 0
                         and t["receive_bytes"] == 0 and ("error" in t["json"] or t["raw"]["exit_code"] == 124)
                         for t in tcp.values()), transfers=tcp)
            self.ev.save("negative-control.json", {"cloud": cloud, "reverse": reverse,
                         "control": control, "tcp_before": pre_tcp, "tcp_cut": tcp})
        finally:
            self.exec("fog", ["ip", "link", "set", "dev", self.fog_wan_if, "up"])
        self.phase("path-cut-restored", throughput=True)
        reverse_restored = self.iperf("cloud", self.addresses["edge"], seconds=1)
        self.require("reverse TCP restored after cut", reverse_restored["raw"]["exit_code"] == 0
                     and reverse_restored["receive_bytes"] > 0, transfer=reverse_restored)
        self.ev.save("negative-control-reverse-restored.json", reverse_restored)

    def cleanup_resources(self):
        if self.client is None:
            return
        import docker
        # Exact returned IDs, plus recovery of exact planned names with our label.
        for family in ("containers", "networks"):
            collection = getattr(self.client, family)
            planned = set(self.names.values()) if family == "containers" else self.network_names
            try:
                candidates = collection.list(**({"all": True} if family == "containers" else {}))
            except BaseException as error:
                candidates = []
                self.ledger["cleanup_errors"].append({"operation": "discovery", "family": family, "error": repr(error)})
                self.ev.event("cleanup_discovery_error", family=family, error=repr(error))
            for resource in candidates:
                labels = (resource.labels if family == "containers" else resource.attrs.get("Labels")) or {}
                if resource.name in planned and labels.get(LABEL) == self.token:
                    if not any(r["id"] == resource.id for r in self.ledger[family]):
                        self.ledger[family].append({"id": resource.id, "name": resource.name})
            for row in self.ledger[family]:
                try:
                    resource = collection.get(row["id"])
                    resource.reload()
                    labels = (resource.labels if family == "containers" else resource.attrs.get("Labels")) or {}
                    if resource.name != row["name"] or labels.get(LABEL) != self.token:
                        raise RuntimeError(f"Ownership mismatch: {family} {row}")
                    resource.remove(**({"force": True} if family == "containers" else {}))
                    self.ev.event("resource_removed", family=family, **row)
                except docker.errors.NotFound:
                    self.ev.event("resource_already_absent", family=family, **row)
                except BaseException as error:
                    self.ledger["cleanup_errors"].append({"family": family, "resource": row, "error": repr(error)})
                    self.ev.event("cleanup_error", family=family, resource=row, error=repr(error))
        self.ev.save("ledger.json", self.ledger)

    def run(self):
        status, failure = "FAILED", None
        self.ev.save("plan-before-calibration.json", PLAN)
        try:
            self.preflight()
            self.start()
            self.cycles("calibration", 1)
            self.require("calibration passes without threshold changes", all(r["passed"] for r in self.checks))
            calibration_count = len(self.measurements)
            calibration_bytes = json.dumps(self.measurements, sort_keys=True).encode()
            self.ev.save("frozen-treatment-plan.json", {**PLAN,
                "calibration_sha256": hashlib.sha256(calibration_bytes).hexdigest(),
                "frozen_monotonic_ns": time.monotonic_ns(),
                "scope": self.args.stage})
            if self.args.stage == "full":
                self.cycles("treatment", PLAN["repetitions"])
            self.negative_control()
            status = "PASSED" if all(c["passed"] for c in self.checks) else "FAILED_ACCEPTANCE"
            self.ev.event("trial_complete", status=status, calibration_phases=calibration_count)
        except BaseException as error:
            failure = {"error": repr(error), "traceback": traceback.format_exc()}
            self.ev.event("experiment_failed", **failure)
            print(failure["traceback"], file=sys.stderr)
        finally:
            signal.alarm(0)
            try:
                self.cleanup_resources()
            except BaseException as error:
                self.ledger["cleanup_errors"].append({"error": repr(error)})
                self.ev.event("cleanup_outer_exception", error=repr(error))
            if self.collections:
                cc, nc, old_cc, old_nc = self.collections
                cc.create, nc.create = old_cc, old_nc
            if self.socket:
                self.socket.close()
            if self.context:
                self.context.term()
            if self.client:
                try:
                    after = {"containers": [c.id for c in self.client.containers.list(all=True)],
                             "networks": [n.id for n in self.client.networks.list()]}
                    self.ev.save("docker-inventory-after.json", after)
                    before_path = self.ev.output / "docker-inventory-before.json"
                    if before_path.exists():
                        before = json.loads(before_path.read_text())
                        self.check("guest inventory restored", all(set(after[k]) == set(before[k]) for k in before))
                    else:
                        self.ev.event("cleanup_inventory_comparison_unavailable", reason="preflight failed before baseline capture")
                except BaseException as error:
                    self.ledger["cleanup_errors"].append({"operation": "inventory_after", "error": repr(error)})
                    self.ev.event("cleanup_inventory_failure", error=repr(error))
                finally:
                    self.client.close()
            if self.ledger["cleanup_errors"] or any(not c["passed"] for c in self.checks):
                status = "FAILED" if failure else "FAILED_ACCEPTANCE"
            summary = {"status": status, "stage": self.args.stage, "source_sha": PIN,
                       "token": self.token, "checks": self.checks, "failure": failure,
                       "measurement_phases": len(self.measurements),
                       "cleanup_errors": self.ledger["cleanup_errors"],
                       "limitation": "No Kubernetes, independent hardware, or generic MADT deployment claim"}
            self.ev.save("summary.json", summary)
            self.ev.save("ledger.json", self.ledger)
            print(json.dumps({k: summary[k] for k in ("status", "stage", "measurement_phases", "cleanup_errors")}))
            self.ev.events.close()
        return 0 if status == "PASSED" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", required=True, help="Built endpoint sha256 image ID, never a mutable tag")
    parser.add_argument("--stage", choices=("calibration", "full"), default="full")
    args = parser.parse_args()
    args.source, args.output = args.source.resolve(), args.output.resolve()
    # Running a venv's Python by absolute path does not activate its CLI tools.
    # Point the real upstream shell calls at the same pinned venv's tcconfig.
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    def interrupted(signum, frame):
        raise TimeoutError(f"Signal {signum}; bounded experiment interrupted, cleaning owned resources")
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM):
        signal.signal(signum, interrupted)
    signal.alarm(1100)
    raise SystemExit(Experiment(args).run())


if __name__ == "__main__":
    main()
