"""DAMOV2 3D-stacked (HMC-equivalent) memory — Ramulator2 DSL config.

Ramulator2 has no HMC standard, so DAMOV2 models the paper's Hybrid Memory Cube
(Table 1: 3D-stacked, high bank/vault parallelism, ~8 GB) with HBM2 — the modern
3D-stacked / near-data substrate. This script defines a `mem` memory_system that
`gem5/configs/ramulator2_mem.py` serializes into the `ramulator_config` string
passed to the gem5 `Ramulator2` SimObject.

It can also be run standalone to export a Ramulator2 config:

    python -m ramulator export gem5/ramulator2/hmc.py -o hmc.yaml
"""
import ramulator

# One controller per channel; HBM2's pseudochannel/bankgroup/bank levels give
# the vault- and bank-level parallelism the paper's HMC configuration used.
NUM_CHANNELS = 8

controllers = []
for _ in range(NUM_CHANNELS):
    dram = ramulator.dram.HBM2(org_preset="HBM2_8Gb", timing_preset="HBM2_2000Mbps")
    controllers.append(ramulator.controller.HBM12(
        dram=dram,
        scheduler=ramulator.scheduler.FRFCFS(),
        refresh_manager=ramulator.refresh_manager.AllBank(),
        row_policy=ramulator.row_policy.Open(),          # open-page (Table 1)
        addr_mapper=ramulator.addr_mapper.RoBaRaCoCh(),  # interleave lines across banks
    ))

mem = ramulator.memory_system.GenericDRAM(
    clock_ratio=3,
    controllers=controllers,
    channel_mapper=ramulator.channel_mapper.CacheLineInterleave(),
)

# For standalone `ramulator export`, expose a frontend too.
frontend = ramulator.frontend.External(clock_ratio=1)
