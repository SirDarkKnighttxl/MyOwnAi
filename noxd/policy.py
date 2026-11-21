"""Permission engine. Gates every tool call; modes are ask / auto / yolo."""
from __future__ import annotations

import ipaddress
import pathlib
import shlex

SHELLS = {"cmd", "powershell", "pwsh", "bash", "sh"}


class Verdict:
    def __init__(self, allowed: bool, reason: str) -> None:
        self.allowed = allowed
        self.reason = reason

    def __bool__(self) -> bool:
        return self.allowed


class Policy:
    def __init__(self, cfg: dict) -> None:
        p = cfg.get("policy", {})
        self.mode = p.get("mode", "auto")
        self.roots = [pathlib.Path(r).resolve() for r in p.get("scope_roots", [])]
        self.cidrs = [ipaddress.ip_network(c, strict=False) for c in p.get("scope_cidrs", [])]
        self.bins = {b.lower() for b in p.get("allowed_bins", [])}
        self.airgap = bool(cfg.get("ui", {}).get("airgap", False))

    def check_path(self, raw: str) -> Verdict:
        if self.mode == "yolo" or not self.roots:
            return Verdict(True, "no scope restriction")
        target = pathlib.Path(raw).resolve()
        for root in self.roots:
            if target == root or root in target.parents:
                return Verdict(True, f"inside {root}")
        return Verdict(False, f"outside scope: {target}")

    def check_command(self, command: str) -> Verdict:
        if self.mode == "yolo":
            return Verdict(True, "yolo")
        try:
            argv = shlex.split(command, posix=False)
        except ValueError:
            return Verdict(False, "unparseable command")
        if not argv:
            return Verdict(False, "empty command")

        exe = pathlib.Path(argv[0]).name.lower()
        if exe.endswith(".exe"):
            exe = exe[:-4]
        if self.bins and exe not in self.bins and exe not in SHELLS:
            return Verdict(False, f"binary not in allowlist: {exe}")

        for tok in argv[1:]:
            if tok.startswith("-"):
                continue
            stripped = tok.strip("\"'")
            if "/" in stripped or "\\" in stripped:
                verdict = self.check_path(stripped)
                if not verdict:
                    return verdict
        return Verdict(True, "in scope")

    def check_host(self, host: str) -> Verdict:
        if self.mode == "yolo" or not self.cidrs:
            return Verdict(True, "no cidr scope")
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            return Verdict(True, "unresolved hostname")
        for net in self.cidrs:
            if addr in net:
                return Verdict(True, f"inside {net}")
        return Verdict(False, f"outside scope: {addr}")