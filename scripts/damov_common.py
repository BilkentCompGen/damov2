"""Shared helpers for the DAMOV2 orchestration scripts.

Loads the global config (configs/damov.yaml) and benchmark descriptors, and
computes the canonical output-directory layout:

  <output_root>/<suite>/<function>/<config>/<cores>/     # scaling runs
  <output_root>/<suite>/<function>/trace/                # Step-2 trace run

YAML is parsed with PyYAML if available, otherwise a tiny built-in parser
handles the simple subset used by our config/descriptor files (no anchors, no
flow-mapping beyond inline lists).
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------- #
# Minimal YAML loader (fallback when PyYAML is unavailable)
# --------------------------------------------------------------------------- #
def _load_yaml(path):
    try:
        import yaml  # type: ignore
        with open(path) as f:
            return yaml.safe_load(f)
    except ImportError:
        with open(path) as f:
            return _tiny_yaml(f.read())


def _coerce(v):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [_coerce(x) for x in inner.split(",")] if inner else []
    if v.startswith(('"', "'")) and v.endswith(('"', "'")):
        return v[1:-1]
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def _tiny_yaml(text):
    """Parse the restricted YAML subset used by DAMOV2 config files: nested
    mappings by indentation, inline lists, and `- ` list items of mappings."""
    root = {}
    stack = [(-1, root)]
    lines = [ln.rstrip() for ln in text.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    i = 0
    while i < len(lines):
        line = lines[i]
        indent = len(line) - len(line.lstrip())
        content = line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if content.startswith("- "):
            item = content[2:].strip()
            if not isinstance(parent, list):
                raise ValueError(f"list item without a list parent: {line}")
            if ":" in item:
                d = {}
                k, _, v = item.partition(":")
                d[k.strip()] = _coerce(v) if v.strip() else {}
                parent.append(d)
                stack.append((indent, d))
                # subsequent deeper "key: value" lines attach to this dict
            else:
                parent.append(_coerce(item))
        else:
            key, _, val = content.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                # container: peek next line to decide list vs mapping
                nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
                child = [] if nxt.startswith("- ") else {}
                if isinstance(parent, list):
                    parent[-1][key] = child
                else:
                    parent[key] = child
                stack.append((indent, child))
            else:
                if isinstance(parent, list):
                    parent[-1][key] = _coerce(val)
                else:
                    parent[key] = _coerce(val)
        i += 1
    return root


# --------------------------------------------------------------------------- #
# Config / descriptor access
# --------------------------------------------------------------------------- #
def load_config(path=None):
    path = path or os.path.join(REPO_ROOT, "configs", "damov.yaml")
    cfg = _load_yaml(path)
    cfg.setdefault("output_root", "out")
    cfg.setdefault("cores", [1, 4, 16, 64, 256])
    cfg.setdefault("configs", ["host_ooo", "host_prefetch", "ndp"])
    cfg.setdefault("classify_config", "host_ooo")
    cfg.setdefault("cpu_type", "O3")
    cfg.setdefault("tools_dir", "build")

    # Environment overrides (used by the SLURM scripts so paths need not be
    # hard-coded in configs/damov.yaml on shared clusters).
    env_map = {
        "DAMOV2_GEM5_BIN": "gem5_binary",
        "DAMOV2_GEM5_CONFIG": "gem5_config",
        "DAMOV2_RAMULATOR_CONFIG": "ramulator_config",
        "DAMOV2_CPU_TYPE": "cpu_type",
        "DAMOV2_TOOLS_DIR": "tools_dir",
        "DAMOV2_OUTPUT_ROOT": "output_root",
    }
    for env, key in env_map.items():
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


def load_descriptor(path):
    d = _load_yaml(path)
    if "functions" not in d:
        raise ValueError(f"{path}: descriptor needs a 'functions' list")
    d.setdefault("suite", os.path.splitext(os.path.basename(path))[0])
    return d


def abspath(p):
    return p if os.path.isabs(p) else os.path.join(REPO_ROOT, p)


def tool(cfg, name):
    return abspath(os.path.join(cfg["tools_dir"], name))


def out_dir(cfg, suite, function, config=None, cores=None, trace=False):
    base = os.path.join(abspath(cfg["output_root"]), suite, function)
    if trace:
        return os.path.join(base, "trace")
    return os.path.join(base, config, str(cores))


def eprint(*a):
    print(*a, file=sys.stderr)
