#!/usr/bin/env bash
set -euo pipefail

GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
NC="\033[0m"

ROOT_DIR="/opt/ssh-vpn-admin"
LAUNCHER="/usr/local/bin/ssh-vpn-admin"
REPO_URL="https://github.com/USERNAME/REPO.git"

trap 'echo -e "${RED}Error: install failed at line ${LINENO}.${NC}"; exit 1' ERR

run_step() {
  local message="$1"
  shift
  echo -e "${GREEN}${message}${NC}"
  "$@"
}

if [ "${EUID}" -ne 0 ]; then
  echo -e "${RED}Error: must run as root.${NC}"
  exit 1
fi

if [ -f /etc/os-release ]; then
  if ! grep -q "Ubuntu 24.04" /etc/os-release; then
    echo -e "${YELLOW}Warning: designed for Ubuntu 24.04.${NC}"
  fi
fi

if [ -d "${ROOT_DIR}" ]; then
  echo -e "${YELLOW}Already installed. Run: sudo ssh-vpn-admin --update${NC}"
  exit 0
fi

run_step "Installing system dependencies..." apt-get update -y
run_step "Installing system dependencies..." apt-get install -y python3 python3-pip python3-venv git openssh-server iptables

run_step "Cloning repository..." git clone "${REPO_URL}" "${ROOT_DIR}"

version="unknown"
if [ -f "${ROOT_DIR}/VERSION" ]; then
  version="$(cat "${ROOT_DIR}/VERSION")"
fi

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN} SSH VPN Admin TUI v${version} ${NC}"
echo -e "${GREEN}======================================${NC}"

cd "${ROOT_DIR}"

run_step "Creating virtual environment..." python3 -m venv .venv

run_step "Installing Python dependencies..." .venv/bin/pip install -r requirements.txt

run_step "Creating launcher..." bash -c "cat > '${LAUNCHER}' <<'EOF'
#!/usr/bin/env bash
exec /opt/ssh-vpn-admin/.venv/bin/python /opt/ssh-vpn-admin/main.py "$@"
EOF
"
run_step "Creating launcher..." chmod +x "${LAUNCHER}"


run_step "Initializing database..." .venv/bin/python main.py --init-db


echo -e "${GREEN}Install complete.${NC}"
echo -e "Run: ${GREEN}sudo ssh-vpn-admin${NC}"
echo -e "Update: ${GREEN}sudo ssh-vpn-admin --update${NC}"
echo -e "Uninstall: ${GREEN}sudo ssh-vpn-admin --uninstall${NC}"
