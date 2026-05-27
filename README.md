# SSH VPN Admin TUI
Production-ready terminal admin tool for managing SSH VPN users on Ubuntu 24.04.

![MIT](https://img.shields.io/badge/License-MIT-green)
![Ubuntu](https://img.shields.io/badge/Platform-Ubuntu%2024.04-blue)
![Python](https://img.shields.io/badge/Python-3.12%2B-blue)
![PRs](https://img.shields.io/badge/PRs-welcome-brightgreen)

```
[screenshot — replace with actual terminal screenshot]
```

## Features
- Textual-based TUI dashboard with sortable user table and live refresh
- Linux user hardening (nologin shell, ForceCommand, no TTY)
- SQLite metadata store with audit events
- Traffic accounting with iptables and limit enforcement
- Expiry and traffic reset scheduler
- One-liner installer, updater, and uninstaller

## Requirements
- Ubuntu 24.04 (other distros may work)
- Python 3.12+
- Root access
- openssh-server
- git

## Installation

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/shayanrsh/SSH-VPN-TUI/main/install.sh)
```

Manual install:

```bash
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git openssh-server iptables
sudo git clone https://github.com/shayanrsh/SSH-VPN-TUI.git /opt/ssh-vpn-admin
cd /opt/ssh-vpn-admin
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo tee /usr/local/bin/ssh-vpn-admin >/dev/null <<'EOF'
#!/usr/bin/env bash
exec /opt/ssh-vpn-admin/.venv/bin/python /opt/ssh-vpn-admin/main.py "$@"
EOF
sudo chmod +x /usr/local/bin/ssh-vpn-admin
sudo /opt/ssh-vpn-admin/.venv/bin/python /opt/ssh-vpn-admin/main.py --init-db
```

## Usage

Launch:

```bash
sudo ssh-vpn-admin
```

Shortcuts:

| Key   | Action         |
| ----- | -------------- |
| N     | New user       |
| Enter | View/Edit user |
| D     | Disable/Enable |
| X     | Delete user    |
| R     | Reset traffic  |
| U     | Update         |
| /     | Search/filter  |
| Q     | Quit           |

## How SSH VPN Works

To open a SOCKS5 proxy tunnel:

```bash
ssh -D 1080 -N username@your-server
```

Then configure your browser or OS network settings to use a SOCKS5 proxy at `127.0.0.1:1080`.

## Updating

```bash
sudo ssh-vpn-admin --update
```

## Uninstalling

```bash
sudo ssh-vpn-admin --uninstall
```

## Security
- Users are created with `/usr/sbin/nologin` and no TTY access
- `ForceCommand /bin/false` blocks shell execution
- `AllowTcpForwarding yes` with `GatewayPorts no`
- sshd configuration is validated with `sshd -t` and rolled back on failure

## Configuration
Edit constants in [config.py](config.py):
- `DB_PATH` and `LOG_PATH` for storage locations
- Scheduler intervals (`TRAFFIC_SAMPLE_SECONDS`, `EXPIRY_CHECK_SECONDS`)
- sshd config path for VPN user Match blocks

## Contributing
Open issues and PRs on GitHub. See [bug report](.github/ISSUE_TEMPLATE/bug_report.md) and [feature request](.github/ISSUE_TEMPLATE/feature_request.md) templates.

## License
MIT. See [LICENSE](LICENSE).