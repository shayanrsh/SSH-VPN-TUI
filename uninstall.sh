#!/usr/bin/env bash
set -euo pipefail

GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
NC="\033[0m"

ROOT_DIR="/opt/ssh-vpn-admin"
LAUNCHER="/usr/local/bin/ssh-vpn-admin"
DB_FILE="/var/lib/ssh-vpn-admin/ssh_vpn_admin.db"
LOG_FILE="/var/log/ssh-vpn-admin.log"

trap 'echo -e "${RED}Error: uninstall failed at line ${LINENO}.${NC}"; exit 1' ERR

if [ "${EUID}" -ne 0 ]; then
  echo -e "${RED}Error: must run as root.${NC}"
  exit 1
fi

echo -e "${RED}+-----------------------------------------------------------+${NC}"
echo -e "${RED}| WARNING: This will remove ssh-vpn-admin but will NOT      |${NC}"
echo -e "${RED}| touch Linux VPN user accounts or the sshd config.         |${NC}"
echo -e "${RED}+-----------------------------------------------------------+${NC}"

read -r -p "Type UNINSTALL to confirm: " confirm
if [ "${confirm}" != "UNINSTALL" ]; then
  echo -e "${YELLOW}Uninstall canceled.${NC}"
  exit 0
fi

removed_launcher="no"
removed_root="no"
removed_db="no"
removed_log="no"

if [ -f "${LAUNCHER}" ]; then
  rm -f "${LAUNCHER}"
  removed_launcher="yes"
fi

if [ -d "${ROOT_DIR}" ]; then
  rm -rf "${ROOT_DIR}"
  removed_root="yes"
fi

read -r -p "Remove database file at ${DB_FILE}? [y/N] " reply
if [ "${reply}" = "y" ] || [ "${reply}" = "Y" ]; then
  rm -f "${DB_FILE}"
  removed_db="yes"
fi

read -r -p "Remove log file at ${LOG_FILE}? [y/N] " reply
if [ "${reply}" = "y" ] || [ "${reply}" = "Y" ]; then
  rm -f "${LOG_FILE}"
  removed_log="yes"
fi

echo -e "${GREEN}Removal summary:${NC}"
echo -e "Launcher removed: ${removed_launcher}"
echo -e "Install directory removed: ${removed_root}"
echo -e "Database removed: ${removed_db}"
echo -e "Log removed: ${removed_log}"
echo -e "${YELLOW}Remaining: sshd config and Linux users were not modified.${NC}"
