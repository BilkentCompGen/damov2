"""Build a Ramulator2 `ramulator_config` string for the gem5 wrapper.

Ramulator2 v2.1 integrates with gem5 as an `AbstractMemory` SimObject named
`Ramulator2` (from external/ramulator2/resources/gem5_wrappers/). That SimObject
takes a single string parameter, `ramulator_config`, which is a JSON document of
the form:

    {"frontend": {"impl": "External", "clock_ratio": 1},
     "memory_system": <serialized ramulator memory_system>}

This module builds that string from Ramulator2's Python DSL (the `ramulator`
package under external/ramulator2/python), so DAMOV2 can select a memory model
by name ("hmc" | "hbm2" | "ddr4") or point at a custom DSL / YAML / JSON config.

It is intentionally light: `import ramulator` happens lazily inside
`build_config_string`, so importing this module does not require Ramulator2 to be
installed until a memory is actually built.
"""
import json
import os
import sys


def ensure_ramulator_on_path(ramulator_home=None):
    """Put Ramulator2's `python/` package dir on sys.path and return its home."""
    home = ramulator_home or os.environ.get("RAMULATOR2_HOME")
    if not home:
        here = os.path.dirname(os.path.abspath(__file__))
        home = os.path.abspath(os.path.join(here, "..", "..", "external", "ramulator2"))
    py = os.path.join(home, "python")
    if os.path.isdir(py) and py not in sys.path:
        sys.path.insert(0, py)
    return home


def _hbm2_memory_system(ramulator, channels, org="HBM2_8Gb", timing="HBM2_2000Mbps"):
    """3D-stacked (HMC-equivalent) memory: HBM2 with high bank parallelism.

    Ramulator2 has no HMC standard, so DAMOV2 models the paper's Hybrid Memory
    Cube with HBM2 — the modern 3D-stacked/NDP substrate. Each channel maps to
    one controller; HBM2's pseudochannel/bankgroup/bank levels give the vault-
    and bank-level parallelism the paper's HMC config relied on."""
    controllers = []
    for _ in range(channels):
        dram = ramulator.dram.HBM2(org_preset=org, timing_preset=timing)
        controllers.append(ramulator.controller.HBM12(
            dram=dram,
            scheduler=ramulator.scheduler.FRFCFS(),
            refresh_manager=ramulator.refresh_manager.AllBank(),
            row_policy=ramulator.row_policy.Open(),          # open-page (Table 1)
            addr_mapper=ramulator.addr_mapper.RoBaRaCoCh(),  # interleave lines across banks
        ))
    return ramulator.memory_system.GenericDRAM(
        clock_ratio=3,
        controllers=controllers,
        channel_mapper=ramulator.channel_mapper.CacheLineInterleave(),
    )


def _ddr4_memory_system(ramulator, channels, org="DDR4_8Gb_x8", timing="DDR4_2400R"):
    """Commodity off-chip DDR4 baseline (host-CPU sensitivity studies)."""
    controllers = []
    for _ in range(channels):
        dram = ramulator.dram.DDR4(org_preset=org, timing_preset=timing, rank=2)
        controllers.append(ramulator.controller.GenericDDR(
            dram=dram,
            scheduler=ramulator.scheduler.FRFCFS(),
            refresh_manager=ramulator.refresh_manager.AllBank(),
            row_policy=ramulator.row_policy.Open(),
            addr_mapper=ramulator.addr_mapper.RoBaRaCoCh(),
        ))
    return ramulator.memory_system.GenericDRAM(
        clock_ratio=4,
        controllers=controllers,
        channel_mapper=ramulator.channel_mapper.CacheLineInterleave(),
    )


_PRESETS = {
    "hmc": _hbm2_memory_system,
    "hbm2": _hbm2_memory_system,
    "3dstacked": _hbm2_memory_system,
    "ddr4": _ddr4_memory_system,
    "dram": _ddr4_memory_system,
}


def build_config_string(spec, channels=8, ramulator_home=None):
    """Return the `ramulator_config` JSON string for `spec`.

    `spec` is one of:
      * a preset name: "hmc" / "hbm2" / "ddr4"
      * a path to a Ramulator2 DSL script (.py) exposing a `mem` (or `mem_sys`)
        memory_system object
      * a path to a Ramulator2 YAML/JSON config, used verbatim
    """
    s = str(spec).strip()
    low = s.lower()

    # Verbatim config files (already in Ramulator2's own format).
    if os.path.isfile(s) and (s.endswith(".yaml") or s.endswith(".yml") or s.endswith(".json")):
        with open(s) as f:
            return f.read()

    ensure_ramulator_on_path(ramulator_home)
    try:
        import ramulator  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "Ramulator2's python package not found. Set RAMULATOR2_HOME or run "
            "`git submodule update --init external/ramulator2` and build it "
            f"(see gem5/README.md). Original error: {e}")

    if low in _PRESETS:
        mem = _PRESETS[low](ramulator, channels)
    elif os.path.isfile(s) and s.endswith(".py"):
        ns = {}
        with open(s) as f:
            exec(compile(f.read(), s, "exec"), {"ramulator": ramulator}, ns)
        mem = ns.get("mem") or ns.get("mem_sys")
        if mem is None:
            raise ValueError(f"{s}: DSL script must define `mem` (a memory_system)")
    else:
        raise ValueError(
            f"unknown ramulator spec '{spec}': use a preset "
            f"({', '.join(sorted(set(_PRESETS)))}) or a .py/.yaml/.json path")

    config = {
        "frontend": {"impl": "External", "clock_ratio": 1},
        "memory_system": mem.to_config(),
    }
    return json.dumps(config)


# Allow `python ramulator2_mem.py hmc` to print the config string (debugging /
# for exporting a standalone config).
if __name__ == "__main__":
    spec = sys.argv[1] if len(sys.argv) > 1 else "hmc"
    print(build_config_string(spec))
