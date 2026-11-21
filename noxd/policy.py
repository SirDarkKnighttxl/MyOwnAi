"""Permission engine. Gates every tool call; modes are ask / auto / yolo."""
from __future__ import annotations

import ipaddress
import pathlib
import shlex
import threading

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
        self._session_grants: set[str] = set()
        self._once_grants: set[tuple[str, str]] = set()
        self._grant_lock = threading.Lock()

    def check_path(self, raw: str) -> Verdict:
        if self.mode == "yolo" or not self.roots:
            return Verdict(True, "no scope restriction")
        return self._check_scope_path(raw)

    def _check_scope_path(self, raw: str, cwd: str | None = None) -> Verdict:
        target = pathlib.Path(raw)
        if cwd and not target.is_absolute():
            target = pathlib.Path(cwd) / target
        target = target.resolve()
        for root in self.roots:
            if target == root or root in target.parents:
                return Verdict(True, f"inside {root}")
        return Verdict(False, f"outside scope: {target}")

    @staticmethod
    def _parse_command(command: str) -> tuple[list[str], Verdict | None]:
        try:
            argv = shlex.split(command, posix=False)
        except ValueError:
            return [], Verdict(False, "unparseable command")
        if not argv:
            return [], Verdict(False, "empty command")
        return argv, None

    @staticmethod
    def _binary(argv: list[str]) -> str:
        exe = pathlib.Path(argv[0].strip("\"'")).name.lower()
        if exe.endswith(".exe"):
            exe = exe[:-4]
        return exe

    @staticmethod
    def _grant_key(command: str, cwd: str | None) -> tuple[str, str]:
        resolved = pathlib.Path(cwd or ".").resolve()
        return command, str(resolved).casefold()

    def binary_name(self, command: str) -> str:
        argv, error = self._parse_command(command)
        return "" if error else self._binary(argv)

    def _command_scope(self, argv: list[str], cwd: str | None) -> Verdict:
        if cwd:
            verdict = self._check_scope_path(cwd)
            if not verdict:
                return verdict
        exe = self._binary(argv)
        if self.bins and exe not in self.bins and exe not in SHELLS:
            return Verdict(False, f"binary not in allowlist: {exe}")
        for tok in argv[1:]:
            stripped = tok.strip("\"'")
            if tok.startswith("-") or (
                stripped.startswith("/")
                and len(stripped) <= 12
                and stripped[1:].replace("?", "").isalpha()
            ):
                continue
            if "/" in stripped or "\\" in stripped:
                verdict = self._check_scope_path(stripped, cwd)
                if not verdict:
                    return verdict
        return Verdict(True, "in scope")

    def needs_command_approval(self, command: str, cwd: str) -> bool:
        argv, error = self._parse_command(command)
        if error or self.mode == "yolo":
            return False
        binary = self._binary(argv)
        with self._grant_lock:
            if binary in self._session_grants:
                return False
        if self.mode == "ask":
            return True
        if self.mode != "auto":
            return False
        if self.bins and binary not in self.bins and binary not in SHELLS:
            return False
        return not self._command_scope(argv, cwd)

    def grant_command(self, command: str, cwd: str, for_session: bool) -> None:
        argv, error = self._parse_command(command)
        if error:
            return
        with self._grant_lock:
            if for_session:
                self._session_grants.add(self._binary(argv))
            else:
                self._once_grants.add(self._grant_key(command, cwd))

    def inherit_session_grants(self, other: "Policy") -> None:
        with other._grant_lock:
            grants = set(other._session_grants)
        with self._grant_lock:
            self._session_grants.update(grants)

    def check_command(self, command: str, cwd: str | None = None) -> Verdict:
        argv, error = self._parse_command(command)
        if error:
            return error
        binary = self._binary(argv)
        key = self._grant_key(command, cwd)
        with self._grant_lock:
            if binary in self._session_grants:
                return Verdict(True, f"session grant: {binary}")
            if key in self._once_grants:
                self._once_grants.remove(key)
                return Verdict(True, "one-time grant")
        if self.mode == "yolo":
            return Verdict(True, "yolo")
        if self.mode == "ask":
            return Verdict(False, "approval required")
        return self._command_scope(argv, cwd)

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