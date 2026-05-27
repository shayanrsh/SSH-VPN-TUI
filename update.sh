#!/usr/bin/env bash
set -euo pipefail

GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
NC="\033[0m"

ROOT_DIR="/opt/ssh-vpn-admin"
VERSION_FILE="${ROOT_DIR}/VERSION"

trap 'echo -e "${RED}Error: update failed at line ${LINENO}.${NC}"; exit 1' ERR

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

if [ ! -d "${ROOT_DIR}" ]; then
  echo -e "${RED}Not installed. Run install.sh first.${NC}"
  exit 1
fi

version="unknown"
if [ -f "${VERSION_FILE}" ]; then
  version="$(cat "${VERSION_FILE}")"
fi

echo -e "${GREEN}Current version: v${version}${NC}"

run_step "Fetching updates..." git -C "${ROOT_DIR}" fetch origin

LOCAL_HEAD=$(git -C "${ROOT_DIR}" rev-parse HEAD)
REMOTE_HEAD=$(git -C "${ROOT_DIR}" rev-parse origin/main)

if [ "${LOCAL_HEAD}" = "${REMOTE_HEAD}" ]; then
  echo -e "${GREEN}Already on latest version (v${version}).${NC}"
  exit 0
fi

echo -e "${YELLOW}Updates available:${NC}"
git -C "${ROOT_DIR}" log HEAD..origin/main --oneline

echo -n "Proceed with update? [Y/n] "
read -r reply
if [ -n "${reply}" ] && [ "${reply}" != "Y" ] && [ "${reply}" != "y" ]; then
  echo -e "${YELLOW}Update canceled.${NC}"
  exit 0
fi

run_step "Pulling changes..." git -C "${ROOT_DIR}" pull origin main

run_step "Updating Python dependencies..." "${ROOT_DIR}/.venv/bin/pip" install -r "${ROOT_DIR}/requirements.txt"

NEW_VERSION="$(cat "${VERSION_FILE}")"
if [ "${version}" != "${NEW_VERSION}" ]; then
  run_step "Running migrations..." "${ROOT_DIR}/.venv/bin/python" "${ROOT_DIR}/main.py" --init-db
fi

echo -e "${GREEN}Updated to v${NEW_VERSION} successfully. Restart ssh-vpn-admin to apply.${NC}"
