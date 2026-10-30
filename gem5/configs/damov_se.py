"""DAMOV2 gem5 SE-mode driver.

Builds one of the three DAMOV system configurations (host_ooo, host_prefetch,
ndp) with a Ramulator2-modeled HMC main memory and runs a ROI-annotated
workload. Supports:

  * scalability sweeps over core counts {1,4,16,64,256} (Table 1),
  * out-of-order (O3) or in-order (TimingSimple) cores (Section 3.5.2),
  * region-of-interest fast-forwarding: an AtomicSimple CPU warms up until the
    first damov_work_begin (m5_work_begin), then gem5 switches to the detailed
    CPU + Ramulator2 for the region of interest,
  * optional CommMonitor memory-trace dumping for Step-2 locality analysis.

Run (example):
  build/X86/gem5.opt gem5/configs/damov_se.py \
      --config host_ooo --cores 4 --cpu-type O3 \
      --ramulator-config gem5/ramulator2/HMC-config.yaml \
      --cmd workloads/STREAM/stream_omp --options "" \
      --output-dir out/stream_Add/host_ooo/4

This script targets a gem5 built with the Ramulator2 memory model. It uses only
the stable m5.objects API and degrades gracefully (clear error) if Ramulator2 is
not compiled in.
"""
import argparse
import os
import sys

import m5
from m5.objects import (
    System, SrcClockDomain, VoltageDomain, AddrRange,
    SEWorkload, Process, SystemXBar, L2XBar, Root, CommMonitor, Addr,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import caches           # noqa: E402  (local module, see gem5/configs/caches.py)
import ramulator2_mem   # noqa: E402  (builds the Ramulator2 config string)


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #
def parse_args():
    p = argparse.ArgumentParser(description="DAMOV2 gem5 SE driver")
    p.add_argument("--config", choices=["host_ooo", "host_prefetch", "ndp"],
                   default="host_ooo")
    p.add_argument("--cores", type=int, default=1)
    p.add_argument("--cpu-type", choices=["O3", "Timing"], default="O3",
                   help="detailed CPU model: O3 (out-of-order) or Timing (in-order)")
    p.add_argument("--freq", default="2.4GHz")
    p.add_argument("--mem-size", default="8GB")
    p.add_argument("--ramulator-config", required=True,
                   help="Ramulator2 memory: preset name (hmc/hbm2/ddr4) or a "
                        ".py DSL / .yaml / .json config path")
    p.add_argument("--ramulator-home", default="",
                   help="Ramulator2 checkout (default: external/ramulator2, or "
                        "$RAMULATOR2_HOME)")
    p.add_argument("--mem-channels", type=int, default=8,
                   help="number of Ramulator2 memory channels")
    p.add_argument("--cmd", required=True, help="workload binary")
    p.add_argument("--options", default="", help="workload arguments")
    p.add_argument("--input", default="", help="stdin redirect file")
    p.add_argument("--output-dir", default="m5out")
    p.add_argument("--max-insts", type=int, default=0,
                   help="stop after N instructions in the ROI (0 = run to completion)")
    p.add_argument("--roi-switch", action="store_true", default=True,
                   help="warm up atomically, switch to detailed CPU at ROI begin")
    p.add_argument("--no-roi-switch", dest="roi_switch", action="store_false")
    p.add_argument("--trace", action="store_true",
                   help="attach a CommMonitor and dump a memory trace for Step 2")
    p.add_argument("--trace-file", default="",
                   help="destination for the memory trace (default <output-dir>/trace.gz)")
    return p.parse_args()


# --------------------------------------------------------------------------- #
# CPU model selection
# --------------------------------------------------------------------------- #
def make_cpu(cpu_type, detailed, cpu_id):
    """Return a CPU object. `detailed` selects the timing model used inside the
    ROI; the warm-up CPU is always AtomicSimple for speed."""
    from m5.objects import AtomicSimpleCPU
    if not detailed:
        return AtomicSimpleCPU(cpu_id=cpu_id)
    if cpu_type == "O3":
        # 4-wide out-of-order, 128-entry ROB, 32-entry LSQ (Table 1).
        from m5.objects import DerivO3CPU
        cpu = DerivO3CPU(cpu_id=cpu_id)
        cpu.numROBEntries = 128
        cpu.LQEntries = 32
        cpu.SQEntries = 32
        cpu.fetchWidth = cpu.decodeWidth = cpu.issueWidth = cpu.commitWidth = 4
        cpu.numPhysIntRegs = 256
        cpu.numPhysFloatRegs = 256
        return cpu
    # In-order 4-wide (Table 1 in-order variant).
    from m5.objects import TimingSimpleCPU
    return TimingSimpleCPU(cpu_id=cpu_id)


def setup_interrupts(cpu, system):
    """x86 requires a local APIC per thread, with its PIO and interrupt ports
    hung off the membus; gem5 fatals at instantiate otherwise. Only active
    (non-switched-out) CPUs need this — switched-out CPUs skip the check and
    take over the controller during m5.switchCpus()."""
    cpu.createInterruptController()
    cpu.interrupts[0].pio = system.membus.mem_side_ports
    cpu.interrupts[0].int_requestor = system.membus.cpu_side_ports
    cpu.interrupts[0].int_responder = system.membus.mem_side_ports


# --------------------------------------------------------------------------- #
# Cache hierarchy per configuration
# --------------------------------------------------------------------------- #
def connect_caches(system, args):
    """Wire the per-core private caches and (for host configs) the shared L3.

    Returns the memory-side port that main memory must connect to."""
    membus = SystemXBar()
    system.membus = membus

    if args.config == "ndp":
        # NDP: single private L1 per core, no L2/L3, no prefetcher; L1 connects
        # straight to the (in-logic-layer) DRAM via the membus.
        for i, cpu in enumerate(system.cpu):
            l1d = caches.NDPL1DCache()
            l1i = caches.L1ICache()
            cpu.addPrivateSplitL1Caches(l1i, l1d)
            cpu.icache.mem_side = membus.cpu_side_ports
            cpu.dcache.mem_side = membus.cpu_side_ports
            # Page-table-walker ports must be connected too: SE-mode execution
            # never uses them (walks are functional), but m5.switchCpus() calls
            # BaseMMU::takeOverFrom, which asserts the old walker ports are bound.
            cpu.mmu.connectWalkerPorts(membus.cpu_side_ports, membus.cpu_side_ports)
        return membus

    # host_ooo / host_prefetch: private L1 + private L2 per core, shared L3.
    l3 = caches.make_l3()
    system.l3 = l3
    l3bus = L2XBar()          # bus in front of the shared L3
    system.l3bus = l3bus
    l3.cpu_side = l3bus.mem_side_ports
    l3.mem_side = membus.cpu_side_ports

    for i, cpu in enumerate(system.cpu):
        l1i = caches.L1ICache()
        l1d = caches.L1DCache()
        l2 = (caches.L2CacheWithPrefetcher()
              if args.config == "host_prefetch" else caches.L2Cache())
        l2bus = L2XBar()
        setattr(system, f"l2bus{i}", l2bus)
        setattr(system, f"l2_{i}", l2)

        # addPrivateSplitL1Caches parents the L1s to the CPU and records them in
        # _cached_ports, which m5.switchCpus()/takeOverFrom rely on — wiring the
        # ports by hand instead breaks the ROI CPU switch.
        cpu.addPrivateSplitL1Caches(l1i, l1d)
        cpu.icache.mem_side = l2bus.cpu_side_ports
        cpu.dcache.mem_side = l2bus.cpu_side_ports
        # Walker ports route through the per-core L2 bus. Needed for the ROI CPU
        # switch: BaseMMU::takeOverFrom asserts the old walker ports are bound.
        cpu.mmu.connectWalkerPorts(l2bus.cpu_side_ports, l2bus.cpu_side_ports)
        l2.cpu_side = l2bus.mem_side_ports
        l2.mem_side = l3bus.cpu_side_ports

    return membus


# --------------------------------------------------------------------------- #
# Ramulator2 main memory (replaces the original DAMOV's Ramulator v1)
# --------------------------------------------------------------------------- #
def connect_memory(system, args, mem_source_port):
    # Ramulator2 v2.1 ships a gem5 wrapper (an AbstractMemory SimObject named
    # `Ramulator2`) that takes a single `ramulator_config` JSON string. That
    # string is produced from Ramulator2's Python DSL by ramulator2_mem.
    try:
        from m5.objects import Ramulator2
    except ImportError:
        m5.fatal("This gem5 build lacks the Ramulator2 memory model. Copy "
                 "external/ramulator2/resources/gem5_wrappers/ into "
                 "gem5/src/mem/ramulator2/ and rebuild (see gem5/README.md).")

    cfg_string = ramulator2_mem.build_config_string(
        args.ramulator_config,
        channels=args.mem_channels,
        ramulator_home=(args.ramulator_home or None))

    mem_range = AddrRange(args.mem_size)
    system.mem_ranges = [mem_range]
    mem = Ramulator2(ramulator_config=cfg_string, range=mem_range)
    system.mem_ctrl = mem
    mem.port = mem_source_port


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    args = parse_args()
    m5.core.setOutputDir(args.output_dir)

    system = System()
    system.clk_domain = SrcClockDomain(clock=args.freq,
                                       voltage_domain=VoltageDomain())
    # With ROI fast-forward the warm-up CPU is AtomicSimpleCPU, so the system
    # must start in atomic mode; m5.switchCpus() flips it to timing when the
    # detailed CPU takes over (it derives the mode from the incoming CPU).
    # Without ROI switching the detailed (timing/O3) CPU runs from the start.
    system.mem_mode = "atomic" if args.roi_switch else "timing"

    # Work-item (ROI) protocol — contract with hooks/damov_hooks.h, which emits
    # m5_work_begin/end with DAMOV_ROI_WORK_ID=100 and DAMOV_FUNCTION_WORK_ID=101.
    # gem5's num_work_ids defaults to 16, so any workload using these hooks
    # fatals ("workid greater than specified") unless we raise it past 101.
    DAMOV_ROI_WORK_ID = 100
    DAMOV_FUNCTION_WORK_ID = 101
    system.num_work_ids = DAMOV_FUNCTION_WORK_ID + 1
    if args.roi_switch:
        # Track only the ROI work item so the detailed CPU switches in at
        # damov_roi_begin() ("work started count reach") and stats are dumped at
        # damov_roi_end() ("work items exit count reached"); the switch loop
        # below keys off those exit causes.
        system.work_item_id = DAMOV_ROI_WORK_ID
        system.work_begin_exit_count = 1
        system.work_end_exit_count = 1

    # ROI fast-forward: build atomic warm-up CPUs and detailed switch CPUs.
    detailed = not args.roi_switch
    system.cpu = [make_cpu(args.cpu_type, detailed=detailed, cpu_id=i)
                  for i in range(args.cores)]

    mem_port = connect_caches(system, args)

    # Optional memory-trace probe for Step-2 locality analysis. The CommMonitor
    # is inserted between the membus and main memory so it observes the DRAM
    # reference stream (post-cache), which is what the locality tool analyzes.
    mem_source_port = mem_port.mem_side_ports
    if args.trace:
        mon = CommMonitor()
        system.mem_monitor = mon
        # CommMonitor sits between the membus mem-side and main memory so it
        # observes the post-cache DRAM stream. gem5 v25.1 renamed the ports
        # slave/master -> cpu_side_port/mem_side_port.
        mon.cpu_side_port = mem_port.mem_side_ports
        trace_file = args.trace_file or os.path.join(args.output_dir, "trace.gz")
        _attach_trace_probe(mon, trace_file)
        mem_source_port = mon.mem_side_port

    connect_memory(system, args, mem_source_port)

    system.system_port = system.membus.cpu_side_ports

    # Workload / process.
    binary = os.path.abspath(args.cmd)
    system.workload = SEWorkload.init_compatible(binary)
    process = Process()
    process.cmd = [binary] + (args.options.split() if args.options else [])
    if args.input:
        process.input = args.input
    for cpu in system.cpu:
        cpu.workload = process
        cpu.createThreads()
        setup_interrupts(cpu, system)

    root = Root(full_system=False, system=system)

    # ROI switch: run atomically, and when m5_work_begin fires switch to the
    # detailed CPU model (registered below via switch CPUs).
    switch_cpus = None
    if args.roi_switch:
        switch_cpus = [make_cpu(args.cpu_type, detailed=True, cpu_id=i)
                       for i in range(args.cores)]
        for i, scpu in enumerate(switch_cpus):
            scpu.system = system
            scpu.clk_domain = system.clk_domain
            scpu.switched_out = True
            # gem5 validates workload.size() == numThreads for every CPU,
            # including switched-out ones (Simulation.py does the same).
            scpu.workload = system.cpu[i].workload
            # Each switch CPU builds its own ISA/decoder (one createThreads per
            # object is fine). It must NOT share system.cpu[i].isa — two CPUs
            # owning one ISA SimObject segfaults during thread construction.
            # Switched-out CPUs skip the interrupt-controller check and take
            # over the warm-up CPU's controller during m5.switchCpus().
            scpu.createThreads()
        system.switch_cpus = switch_cpus

    m5.instantiate()

    print(f"[DAMOV2] config={args.config} cores={args.cores} "
          f"cpu={args.cpu_type} mem=Ramulator2({os.path.basename(args.ramulator_config)})")

    exit_event = m5.simulate()
    # Handle the work-begin/end + switch protocol.
    while True:
        cause = exit_event.getCause()
        if args.roi_switch and "work started" in cause:
            m5.switchCpus(system, list(zip(system.cpu, switch_cpus)))
            m5.stats.reset()
            exit_event = m5.simulate()
            continue
        if "work items exit count reached" in cause or "workend" in cause.lower():
            m5.stats.dump()
            exit_event = m5.simulate()
            continue
        break

    print(f"[DAMOV2] finished @ tick {m5.curTick()} : {exit_event.getCause()}")
    m5.stats.dump()


def _attach_trace_probe(monitor, trace_file):
    """Configure the CommMonitor to emit a DAMOV2 text memory trace.

    gem5's stock CommMonitor emits a protobuf trace. To keep DAMOV2's Step-2
    tool dependency-free we prefer the ASCII format understood by TraceReader.
    Newer gem5 exposes MemTraceProbe; where only the protobuf trace is
    available, convert it with scripts/proto2trace.py."""
    try:
        from m5.objects import MemTraceProbe
        probe = MemTraceProbe(trace_file=trace_file)
        monitor.trace = probe
    except ImportError:
        # Fall back to the protobuf trace; the run script converts it.
        monitor.trace_enable = True
        monitor.trace_file = trace_file.replace(".gz", ".proto.gz")


if __name__ == "__m5_main__" or __name__ == "__main__":
    main()
