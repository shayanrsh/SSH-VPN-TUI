from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Iterable

from config import TrafficBackend
from system import SystemError, get_uid, run_cmd

logger = logging.getLogger(__name__)


class TrafficError(RuntimeError):
    """Traffic accounting error."""
    pass


@dataclass(frozen=True)
class TrafficSample:
    """Traffic usage sample for a user."""
    username: str
    used_bytes: int


def detect_backend() -> str:
    """Detect available traffic accounting backend."""
    if run_cmd(["iptables", "-V"]).returncode == 0:
        return TrafficBackend.IPTABLES
    if run_cmd(["vnstat", "--version"]).returncode == 0:
        return TrafficBackend.VNSTAT
    return TrafficBackend.NONE


def ensure_iptables_rules(username: str) -> None:
    """Ensure per-user iptables rules exist for accounting."""
    uid = get_uid(username)
    for chain in ("OUTPUT", "INPUT"):
        check = run_cmd(
            ["iptables", "-C", chain, "-m", "owner", "--uid-owner", str(uid), "-j", "ACCEPT"]
        )
        if check.returncode != 0:
            add = run_cmd(
                ["iptables", "-A", chain, "-m", "owner", "--uid-owner", str(uid), "-j", "ACCEPT"]
            )
            if add.returncode != 0:
                raise TrafficError(f"iptables add failed: {add.stderr}")


def _parse_iptables_bytes(output: str, uid: int) -> int:
    """Parse iptables byte counters for a given UID."""
    total = 0
    pattern = re.compile(r"^(\d+)\s+(\d+)\s+.*owner UID match\s+%d" % uid)
    for line in output.splitlines():
        match = pattern.search(line)
        if match:
            total += int(match.group(2))
    return total


def read_iptables_bytes(username: str) -> int:
    """Read total iptables byte counters for a user."""
    uid = get_uid(username)
    out = run_cmd(["iptables", "-nvxL", "OUTPUT"]).stdout
    inc = run_cmd(["iptables", "-nvxL", "INPUT"]).stdout
    return _parse_iptables_bytes(out, uid) + _parse_iptables_bytes(inc, uid)


def read_vnstat_bytes(username: str) -> int:
    """Return usage from vnstat when supported."""
    _ = username
    return 0


def reset_iptables_counters(username: str) -> None:
    """Zero iptables counters for the given user."""
    uid = get_uid(username)
    for chain in ("OUTPUT", "INPUT"):
        result = run_cmd(
            ["iptables", "-Z", chain, "-m", "owner", "--uid-owner", str(uid)]
        )
        if result.returncode != 0:
            raise TrafficError(f"iptables reset failed: {result.stderr}")


class TrafficManager:
    """Traffic sampling and counter reset helper."""
    def __init__(self) -> None:
        """Initialize traffic manager and detect backend."""
        self.backend = detect_backend()

    def available(self) -> bool:
        """Return True if any backend is available."""
        return self.backend != TrafficBackend.NONE

    def ensure_user(self, username: str) -> None:
        """Prepare traffic accounting for a user."""
        if self.backend == TrafficBackend.IPTABLES:
            ensure_iptables_rules(username)

    def sample(self, usernames: Iterable[str]) -> list[TrafficSample]:
        """Sample traffic usage for a set of users."""
        samples: list[TrafficSample] = []
        if self.backend == TrafficBackend.NONE:
            return samples
        for username in usernames:
            try:
                if self.backend == TrafficBackend.IPTABLES:
                    used = read_iptables_bytes(username)
                else:
                    used = read_vnstat_bytes(username)
                samples.append(TrafficSample(username, used))
            except SystemError as exc:
                logger.error("Traffic sample failed for %s: %s", username, exc)
        return samples

    def reset_user(self, username: str) -> None:
        """Reset traffic counters for a user when supported."""
        if self.backend == TrafficBackend.IPTABLES:
            reset_iptables_counters(username)
