#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=${0:A:h}
PROJECT_DIR=${SCRIPT_DIR:h}
HERMES_ENV_FILE="${HOME}/.hermes/.env"
LAUNCH_AGENT_FILE="${HOME}/Library/LaunchAgents/com.jarvis.bridge.plist"

mkdir -p "${HOME}/.hermes/services" "${HOME}/.hermes/logs" "${HOME}/Library/LaunchAgents"
touch "${HERMES_ENV_FILE}"
chmod 600 "${HERMES_ENV_FILE}"

ensure_value() {
  local key=$1
  local value=$2
  if ! /usr/bin/grep -q "^${key}=" "${HERMES_ENV_FILE}"; then
    /usr/bin/printf '%s=%s\n' "${key}" "${value}" >> "${HERMES_ENV_FILE}"
  fi
}

random_token() {
  /usr/bin/python3 "${PROJECT_DIR}/bridge/jarvis_bridge.py" --generate-token
}

ensure_value API_SERVER_ENABLED true
ensure_value API_SERVER_KEY "$(random_token)"
ensure_value JARVIS_APP_TOKEN "$(random_token)"
ensure_value JARVIS_FILE_ROOTS "${HOME}/Documents"

/bin/cp "${PROJECT_DIR}/bridge/jarvis_bridge.py" "${HOME}/.hermes/services/jarvis_bridge.py"
/bin/chmod 700 "${HOME}/.hermes/services/jarvis_bridge.py"
/bin/cp "${PROJECT_DIR}/launchd/com.jarvis.bridge.plist" "${LAUNCH_AGENT_FILE}"
/bin/chmod 600 "${LAUNCH_AGENT_FILE}"

hermes gateway restart || hermes gateway install --force --start-now --start-on-login

/bin/launchctl bootout "gui/$(/usr/bin/id -u)/com.jarvis.bridge" 2>/dev/null || true
/bin/launchctl bootstrap "gui/$(/usr/bin/id -u)" "${LAUNCH_AGENT_FILE}"
/bin/launchctl enable "gui/$(/usr/bin/id -u)/com.jarvis.bridge"

echo "JARVIS Mac service installed."
echo "Bridge: http://127.0.0.1:8770"
echo "The app token remains stored in ~/.hermes/.env and was not printed."
