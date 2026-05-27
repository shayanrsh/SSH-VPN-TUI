from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_NAME = "ssh-vpn-admin"
PROJECT_ROOT = Path(__file__).resolve().parent
VERSION_FILE = PROJECT_ROOT / "VERSION"


def load_version() -> str:
    """Load the version string from VERSION file."""
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "0.0.0"


VERSION = load_version()

DB_DIR = Path("/var/lib/ssh-vpn-admin")
DB_PATH = DB_DIR / "ssh_vpn_admin.db"
LOG_PATH = Path("/var/log/ssh-vpn-admin.log")

SSHD_CONFIG_DIR = Path("/etc/ssh/sshd_config.d")
SSHD_CONFIG_FILE = SSHD_CONFIG_DIR / "vpn-users.conf"
SSHD_CONFIG_BACKUP = SSHD_CONFIG_DIR / "vpn-users.conf.bak"

DEFAULT_SHELL = "/usr/sbin/nologin"
DEFAULT_HOME_BASE = Path("/home")

TRAFFIC_SAMPLE_SECONDS = 60
EXPIRY_CHECK_SECONDS = 300
UI_REFRESH_SECONDS = 30

DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

MAX_USERNAME_LEN = 32

@dataclass(frozen=True)
class UserStatus:
    """User status values."""
    ACTIVE: str = "active"
    DISABLED: str = "disabled"
    EXPIRED: str = "expired"
    DELETED: str = "deleted"


@dataclass(frozen=True)
class ExpiryMode:
    """Expiry modes for account lifetime."""
    DATE: str = "date"
    DAYS: str = "days"
    WEEKS: str = "weeks"
    MONTHS: str = "months"
    UNLIMITED: str = "unlimited"


@dataclass(frozen=True)
class ResetMode:
    """Traffic reset schedule modes."""
    DAILY: str = "daily"
    WEEKLY: str = "weekly"
    MONTHLY: str = "monthly"
    UNLIMITED: str = "unlimited"


@dataclass(frozen=True)
class TrafficBackend:
    """Traffic accounting backend names."""
    IPTABLES: str = "iptables"
    VNSTAT: str = "vnstat"
    NONE: str = "none"
