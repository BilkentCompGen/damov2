"""DAMOV2 off-chip DDR4 baseline — Ramulator2 DSL config.

A conventional commodity DRAM for host-CPU sensitivity studies (contrast the
in-logic-layer 3D-stacked memory in hmc.py). Defines a `mem` memory_system used
by gem5/configs/ramulator2_mem.py, or exportable standalone:

    python -m ramulator export gem5/ramulator2/ddr4.py -o ddr4.yaml
"""
import ramulator

NUM_CHANNELS = 4

controllers = []
for _ in range(NUM_CHANNELS):
    dram = ramulator.dram.DDR4(org_preset="DDR4_8Gb_x8", timing_preset="DDR4_2400R", rank=2)
    controllers.append(ramulator.controller.GenericDDR(
        dram=dram,
        scheduler=ramulator.scheduler.FRFCFS(),
        refresh_manager=ramulator.refresh_manager.AllBank(),
        row_policy=ramulator.row_policy.Open(),
        addr_mapper=ramulator.addr_mapper.RoBaRaCoCh(),
    ))

mem = ramulator.memory_system.GenericDRAM(
    clock_ratio=4,
    controllers=controllers,
    channel_mapper=ramulator.channel_mapper.CacheLineInterleave(),
)

frontend = ramulator.frontend.External(clock_ratio=1)
