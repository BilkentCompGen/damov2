#!/usr/bin/env python3
"""Migrate original-DAMOV (ZSim) inputs to DAMOV2.

Converts DAMOV *command files* (`simulator/command_files/*_cf`, one
`benchmark,application,function,command` line per hot function) into DAMOV2
benchmark descriptors, and optionally reads DAMOV's config generator
(`simulator/scripts/generate_config_files.py`, V2 as on github.com/biopim/damov)
to carry its sweep -- core counts, system platforms, core versions -- over to
DAMOV2 global configs.

  DAMOV                                  DAMOV2
  -------------------------------------  ---------------------------------------
  command_files/<x>_cf  (one per suite)  benchmarks/damov/<benchmark>.yaml
  line  bench,app,fn,command             functions: - name: <app>_<fn>
  PIM_ROOT                               --pim-root (default {root}/workloads)
  THREADS                                {threads}  (expanded per core count)
  number_of_cores = [...]                cores: [...]            in the config
  platforms host_*/no_prefetch,          configs: [host_ooo, host_prefetch, ndp]
            host_*/prefetch, pim_*
  versions ooo / inorder                 cpu_type: O3 / Timing   (one config each)

The generator script is parsed with `ast`, never executed. See
docs/migrating-from-damov.md for the full mapping and what does not carry over.

Usage:
  scripts/migrate_damov.py ~/damov/simulator/command_files
  scripts/migrate_damov.py ~/damov/simulator/command_files/stream_cf \\
        --generator ~/damov/simulator/scripts/generate_config_files.py
  scripts/migrate_damov.py CF... --pim-root /data/damov/workloads --force
  scripts/migrate_damov.py CF... --dry-run      # print, write nothing
"""
import argparse
import ast
import os
import re
import sys

import damov_common as dc

# DAMOV generator platform template -> DAMOV2 system configuration (Table 1).
PLATFORM_MAP = {
    "host_{0}/no_prefetch": "host_ooo",
    "host_{0}/prefetch": "host_prefetch",
    "pim_{0}": "ndp",
}
# DAMOV core "version" -> DAMOV2 cpu_type (None = no DAMOV2 equivalent).
VERSION_MAP = {"ooo": "O3", "inorder": "Timing", "accelerator": None}
# Output root per version so O3 and Timing sweeps do not overwrite each other.
VERSION_OUTPUT_ROOT = {"ooo": "out", "inorder": "out-inorder"}

# DAMOV generate_config_files.py defaults, used when a list is not found.
DEFAULT_CORES = [1, 4, 16, 20, 32, 40, 64, 80, 112, 128, 256]
DEFAULT_PLATFORMS = list(PLATFORM_MAP)
DEFAULT_VERSIONS = ["ooo"]

# A 256-core O3 gem5 run needs ~60 GB of host RAM (see configs/damov.yaml).
LARGE_CORE_COUNT = 64

warnings = []


def warn(msg):
    warnings.append(msg)
    dc.eprint(f"warning: {msg}")


# --------------------------------------------------------------------------- #
# Generator (generate_config_files.py) -> sweep parameters
# --------------------------------------------------------------------------- #
def read_generator(path):
    """Pull the literal `number_of_cores`, `platforms` and `versions` lists out
    of a DAMOV generate_config_files.py without running it. V1 of the script
    only defines number_of_cores; the other two then fall back to defaults."""
    with open(path) as f:
        tree = ast.parse(f.read(), filename=path)
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in (
                    "number_of_cores", "platforms", "versions"):
                try:
                    value = ast.literal_eval(node.value)
                except ValueError:
                    warn(f"{path}:{node.lineno}: {target.id} is not a literal "
                         f"list; ignoring it")
                    continue
                if target.id in found and found[target.id] != value:
                    warn(f"{path}:{node.lineno}: {target.id} is assigned more "
                         f"than once with different values; using the first")
                    continue
                found.setdefault(target.id, value)

    cores = found.get("number_of_cores")
    if cores is None:
        warn(f"{path}: no number_of_cores list found; using DAMOV's default")
        cores = DEFAULT_CORES
    platforms = found.get("platforms", DEFAULT_PLATFORMS)
    versions = found.get("versions", DEFAULT_VERSIONS)

    configs = []
    for p in platforms:
        mapped = PLATFORM_MAP.get(p)
        if mapped is None:
            warn(f"{path}: platform '{p}' has no DAMOV2 equivalent; skipped "
                 f"(known: {', '.join(PLATFORM_MAP)})")
        elif mapped not in configs:
            configs.append(mapped)
    cpu_versions = []
    for v in versions:
        if v not in VERSION_MAP:
            warn(f"{path}: version '{v}' is unknown; skipped")
        elif VERSION_MAP[v] is None:
            warn(f"{path}: version '{v}' (ZSim accelerator cores) has no gem5 "
                 f"equivalent in DAMOV2; skipped")
        else:
            cpu_versions.append(v)
    return {"cores": [int(c) for c in cores], "configs": configs,
            "versions": cpu_versions}


def render_config(template_text, sweep, version, source):
    """Rewrite the sweep keys of configs/damov.yaml, keeping everything else
    (comments, thresholds, paths) verbatim."""
    note = "# migrated from DAMOV"
    values = {
        "cores": "[" + ", ".join(str(c) for c in sweep["cores"]) + "]",
        "configs": "[" + ", ".join(sweep["configs"]) + "]",
        "cpu_type": VERSION_MAP[version],
        "output_root": VERSION_OUTPUT_ROOT[version],
    }
    seen = set()
    out = []
    for line in template_text.splitlines():
        m = re.match(r"^(\w+):", line)
        if m and m.group(1) in values:
            key = m.group(1)
            seen.add(key)
            line = f"{key}: {values[key]}  {note}"
        out.append(line)
    for key in values:
        if key not in seen:
            out.append(f"{key}: {values[key]}  {note}")
    header = [
        f"# DAMOV2 global configuration migrated from DAMOV's",
        f"#   {source}",
        f"# for core version '{version}' (cpu_type {VERSION_MAP[version]}). "
        f"Generated by",
        f"# scripts/migrate_damov.py; only cores/configs/cpu_type/output_root "
        f"differ",
        f"# from configs/damov.yaml.",
        "",
    ]
    return "\n".join(header + out) + "\n"


# --------------------------------------------------------------------------- #
# Command files -> descriptors
# --------------------------------------------------------------------------- #
def sanitize(name):
    """Function/suite names become directory names under out/."""
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", name)


def parse_command(command, pim_root, where):
    """Split one DAMOV command string into DAMOV2 binary / options / input."""
    command = command.replace("PIM_ROOT", pim_root).replace("THREADS", "{threads}")
    tokens = command.split()
    if not tokens:
        raise ValueError(f"{where}: empty command")
    binary, args, stdin = tokens[0], [], ""
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok == "<" and i + 1 < len(tokens):
            stdin = tokens[i + 1]
            i += 2
            continue
        if tok in (">", ">>", "2>", "|", "&&", ";") or tok.startswith(("<", ">", "|")):
            warn(f"{where}: shell operator '{tok}' is passed to the workload "
                 f"as a literal argument (gem5 SE mode runs no shell)")
        args.append(tok)
        i += 1
    if binary.endswith(".sh"):
        warn(f"{where}: command is a shell script ({os.path.basename(binary)}); "
             f"gem5 SE mode cannot run it. Point 'binary' at the executable it "
             f"launches")
    return binary, " ".join(args), stdin


def read_command_file(path, pim_root):
    """Yield (benchmark, entry) per non-blank, non-comment line."""
    with open(path) as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            where = f"{path}:{lineno}"
            fields = line.split(",", 3)
            if len(fields) != 4:
                raise ValueError(f"{where}: expected "
                                 f"'benchmark,application,function,command', "
                                 f"got {len(fields)} field(s)")
            benchmark, application, function, command = (x.strip() for x in fields)
            if "," in command:
                warn(f"{where}: command contains ','; DAMOV's generator would "
                     f"have truncated it there, DAMOV2 keeps the whole command")
            binary, options, stdin = parse_command(command, pim_root, where)
            yield benchmark, {
                "name": sanitize(f"{application}_{function}"),
                "binary": binary, "options": options, "input": stdin,
                "origin": f"{os.path.basename(path)}:{lineno}",
                "damov_id": f"{benchmark}_{application}_{function}",
            }


def collect(paths, pim_root):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(os.path.join(p, f) for f in os.listdir(p)
                            if os.path.isfile(os.path.join(p, f))
                            and not f.startswith(".")
                            and not f.endswith((".bak", "~")))
        else:
            files.append(p)
    suites = {}
    for path in files:
        for benchmark, entry in read_command_file(path, pim_root):
            suite = sanitize(benchmark)
            fns = suites.setdefault(suite, {"benchmark": benchmark,
                                            "sources": [], "functions": []})
            src = os.path.basename(path)
            if src not in fns["sources"]:
                fns["sources"].append(src)
            names = {f["name"] for f in fns["functions"]}
            if entry["name"] in names:
                base, n = entry["name"], 2
                while f"{base}_{n}" in names:
                    n += 1
                warn(f"{entry['origin']}: duplicate function '{base}' in suite "
                     f"'{suite}' (DAMOV would overwrite the earlier one's "
                     f"configs); renamed to '{base}_{n}'")
                entry["name"] = f"{base}_{n}"
            fns["functions"].append(entry)
    return suites


def yaml_quote(value, where):
    """Quote a scalar so PyYAML and damov_common._tiny_yaml read it back
    identically: no escapes, and no ' #' (the fallback parser strips it)."""
    if re.search(r"[ \t]#", value):
        raise ValueError(f"{where}: value contains ' #', which the DAMOV2 "
                         f"fallback YAML parser treats as a comment: {value!r}")
    if '"' not in value and "\\" not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    raise ValueError(f"{where}: value mixes quote characters: {value!r}")


def render_descriptor(suite, info, upstream):
    lines = [
        f"# DAMOV2 descriptor for DAMOV suite '{info['benchmark']}', migrated "
        f"from DAMOV",
        f"# command file(s) {', '.join(info['sources'])}"
        + (f" ({upstream})" if upstream else "") + " by",
        "# scripts/migrate_damov.py. {threads} expands to the simulated core "
        "count of",
        "# each job (DAMOV's THREADS); {root} to the DAMOV2 repository root.",
        "#",
        "# Binaries must be rebuilt against hooks/compat/zsim_hooks.h (or "
        "ported to",
        "# hooks/damov_hooks.h): ZSim-instrumented builds never trigger the "
        "gem5 ROI.",
        "# See docs/migrating-from-damov.md.",
        "",
        f"suite: {yaml_quote(suite, suite)}",
        "functions:",
    ]
    for fn in info["functions"]:
        where = fn["origin"]
        # Quoted: an unquoted name such as 1_2 would load as the integer 12.
        lines.append(f"  - name: {yaml_quote(fn['name'], where)}"
                     f"    # {where}, DAMOV stats {fn['damov_id']}")
        lines.append(f"    binary: {yaml_quote(fn['binary'], where)}")
        lines.append(f"    options: {yaml_quote(fn['options'], where)}")
        if fn["input"]:
            lines.append(f"    input: {yaml_quote(fn['input'], where)}")
    return "\n".join(lines) + "\n"


def verify_roundtrip(text, suite, info, where):
    """The descriptor must parse back to exactly what we meant, with both YAML
    loaders the pipeline may use."""
    parsers = [("fallback", dc._tiny_yaml)]
    try:
        import yaml  # type: ignore
        parsers.append(("PyYAML", yaml.safe_load))
    except ImportError:
        pass
    for label, parse in parsers:
        d = parse(text)
        got = [(f["name"], f["binary"], f["options"], f.get("input", ""))
               for f in d["functions"]]
        want = [(f["name"], f["binary"], f["options"], f["input"])
                for f in info["functions"]]
        if d.get("suite") != suite or got != want:
            raise RuntimeError(f"{where}: {label} YAML round-trip mismatch; "
                               f"please report this")


def show(path):
    """Path relative to the working directory when inside it, else absolute."""
    path = os.path.abspath(path)
    rel = os.path.relpath(path)
    return path if rel.startswith("..") else rel


def write(path, text, args):
    rel = show(path)
    if args.dry_run:
        print(f"--- {rel} ---")
        print(text)
        return
    if os.path.exists(path) and not args.force:
        raise FileExistsError(f"{rel} exists; pass --force to overwrite")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    print(f"wrote {rel}")


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(
        description="Convert DAMOV command files (and optionally its "
                    "generate_config_files.py sweep) to DAMOV2.")
    ap.add_argument("command_files", nargs="+",
                    help="DAMOV command file(s) or a command_files/ directory")
    ap.add_argument("--generator", default=None,
                    help="DAMOV generate_config_files.py whose sweep to carry "
                         "over into DAMOV2 config(s)")
    ap.add_argument("--out-dir", default=os.path.join(dc.REPO_ROOT, "benchmarks",
                                                      "damov"),
                    help="where descriptors go (default: benchmarks/damov)")
    ap.add_argument("--pim-root", default="{root}/workloads",
                    help="replacement for DAMOV's PIM_ROOT (default: "
                         "'{root}/workloads', i.e. this repo's workloads/)")
    ap.add_argument("--config-template",
                    default=os.path.join(dc.REPO_ROOT, "configs", "damov.yaml"),
                    help="DAMOV2 config to base migrated configs on")
    ap.add_argument("--config-prefix",
                    default=os.path.join(dc.REPO_ROOT, "configs", "damov_migrated"),
                    help="migrated configs are written as <prefix>_<version>.yaml")
    ap.add_argument("--upstream", default="",
                    help="provenance note for descriptor headers, e.g. "
                         "'biopim/damov@4d611a5'")
    ap.add_argument("--force", action="store_true", help="overwrite outputs")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the outputs instead of writing them")
    args = ap.parse_args()

    pim_root = args.pim_root.rstrip("/") or "/"
    try:
        suites = collect(args.command_files, pim_root)
        if not suites:
            dc.eprint("no command lines found")
            return 1
        rendered = []
        for suite, info in sorted(suites.items()):
            text = render_descriptor(suite, info, args.upstream)
            path = os.path.join(args.out_dir, f"{suite}.yaml")
            verify_roundtrip(text, suite, info, path)
            rendered.append((path, text))

        configs = []
        sweep = None
        if args.generator:
            sweep = read_generator(args.generator)
            gen_source = (f"{os.path.basename(args.generator)} ({args.upstream})"
                          if args.upstream else os.path.abspath(args.generator))
            with open(args.config_template) as f:
                template = f.read()
            if not sweep["configs"]:
                raise ValueError(f"{args.generator}: no platform maps to a "
                                 f"DAMOV2 config")
            for version in sweep["versions"]:
                configs.append((f"{args.config_prefix}_{version}.yaml",
                                render_config(template, sweep, version,
                                              gen_source)))
            cfg = dc.load_config(args.config_template)
            if cfg["classify_config"] not in sweep["configs"]:
                warn(f"classify_config '{cfg['classify_config']}' is not in the "
                     f"migrated configs {sweep['configs']}; classification will "
                     f"find no runs")

        for path, text in rendered + configs:
            write(path, text, args)
    except (OSError, ValueError, SyntaxError, RuntimeError) as e:
        dc.eprint(f"error: {e}")
        return 1

    nfn = sum(len(s["functions"]) for s in suites.values())
    no_threads = sum(1 for s in suites.values() for f in s["functions"]
                     if "{threads}" not in f["binary"] + f["options"] + f["input"])
    print(f"\nmigrated {nfn} function(s) in {len(suites)} suite(s); "
          f"{len(warnings)} warning(s)")
    if no_threads:
        print(f"note: {no_threads} function(s) take no THREADS argument; their "
              f"thread count is whatever the workload picks itself")
    if sweep:
        big = [c for c in sweep["cores"] if c > LARGE_CORE_COUNT]
        if big:
            print(f"note: core counts {big} exceed {LARGE_CORE_COUNT}; O3 gem5 "
                  f"runs at that size need tens of GB of host RAM each "
                  f"(set SLURM_MEM accordingly)")
    if not args.dry_run:
        first = rendered[0][0]
        # Point the hint at the O3 config when there is one (the paper's default).
        cfg = next((c for c, _ in configs if c.endswith("_ooo.yaml")),
                   configs[0][0] if configs else None)
        cfg_opt = f" --config {show(cfg)}" if cfg else ""
        print("\nnext: rebuild the workloads against hooks/compat/zsim_hooks.h, "
              "then e.g.")
        print(f"  scripts/damov2_pipeline.py --descriptor "
              f"{show(first)}{cfg_opt} --dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
