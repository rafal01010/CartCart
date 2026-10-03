#!/usr/bin/env bash

source_env_file() {
  local env_file="$1"
  local use_shell_env="${2:-false}"

  if [[ ! -f "${env_file}" ]]; then
    return 0
  fi

  local line key
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"

    if [[ -z "${line}" || "${line}" == \#* ]]; then
      continue
    fi

    if [[ "${line}" == export[[:space:]]* ]]; then
      line="${line#export}"
      line="${line#"${line%%[![:space:]]*}"}"
    fi

    key="${line%%=*}"
    key="${key%"${key##*[![:space:]]}"}"

    if [[ "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && {
      [[ "${use_shell_env}" != "true" ]] || [[ -z "${!key+x}" ]]
    }; then
      set -a
      eval "${line}"
      set +a
    fi
  done <"${env_file}"
}

parse_env_options() {
  USE_SHELL_ENV=false
  if (($# == 1)) && [[ "$1" == "--use-shell-env" ]]; then
    USE_SHELL_ENV=true
  elif (($# > 0)); then
    echo "Error: expected no arguments or --use-shell-env." >&2
    exit 2
  fi
}

require_command() {
  local command_name="$1"
  local purpose="$2"
  local install_hint="$3"

  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Error: ${command_name} is required to ${purpose}." >&2
    echo "${install_hint}" >&2
    exit 1
  fi
}

require_file() {
  local file_path="$1"
  local error_message="$2"
  local fix_hint="$3"

  if [[ ! -f "${file_path}" ]]; then
    echo "Error: ${error_message}" >&2
    echo "${fix_hint}" >&2
    exit 1
  fi
}

read_pid_file() {
  local pid_file="$1"

  if [[ -f "${pid_file}" ]]; then
    local pid
    if ! pid="$(cat "${pid_file}")"; then
      echo "Error: cannot read PID file ${pid_file}." >&2
      return 2
    fi
    if [[ "${pid}" =~ ^[1-9][0-9]*$ ]]; then
      echo "${pid}"
      return 0
    fi
    echo "Error: invalid PID file ${pid_file}; no process was signalled." >&2
    return 2
  fi

  return 1
}

is_pid_running() {
  local pid="$1"
  local failure
  if failure="$(LC_ALL=C kill -0 "${pid}" 2>&1)"; then
    return 0
  fi
  if [[ "${failure}" == *"No such process"* ]]; then
    return 1
  fi
  echo "Error: cannot inspect PID ${pid}; check process permissions. PID file preserved." >&2
  exit 1
}

start_managed_service() {
  local service_name="$1"
  local pid_file="$2"
  local log_file="$3"
  local readiness_url="$4"
  shift 4

  mkdir -p "$(dirname "${pid_file}")" "$(dirname "${log_file}")"

  local existing_pid
  if existing_pid="$(read_pid_file "${pid_file}")"; then
    if is_pid_running "${existing_pid}"; then
      echo "${service_name} is already running with PID ${existing_pid}."
      echo "Use restart-app.sh to reload changed environment settings."
      echo "Log: ${log_file}"
      return 0
    fi
  else
    local pid_status=$?
    if ((pid_status != 1)); then
      exit 1
    fi
  fi

  rm -f "${pid_file}"

  if curl --noproxy '*' --silent --output /dev/null --max-time 1 "${readiness_url}"; then
    echo "Error: ${service_name} address already responds without a managed PID: ${readiness_url}" >&2
    echo "Stop that service before starting another instance." >&2
    exit 1
  fi

  echo "Starting ${service_name}..."
  echo "Log: ${log_file}"
  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] starting ${service_name}: $*" >>"${log_file}"
  nohup "$@" >>"${log_file}" 2>&1 &

  local pid="$!"
  echo "${pid}" >"${pid_file}"

  local waited=0
  while ((waited < 30)); do
    if ! is_pid_running "${pid}"; then
      echo "Error: ${service_name} exited during startup. See ${log_file}." >&2
      rm -f "${pid_file}"
      exit 1
    fi
    if curl --noproxy '*' --fail --silent --output /dev/null --max-time 1 "${readiness_url}"; then
      echo "${service_name} ready with PID ${pid}."
      echo "PID file: ${pid_file}"
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "Error: ${service_name} did not become ready. See ${log_file}." >&2
  echo "PID file preserved; use stop-app.sh before retrying." >&2
  exit 1
}

stop_managed_service() {
  local service_name="$1"
  local pid_file="$2"

  local pid
  if pid="$(read_pid_file "${pid_file}")"; then
    :
  else
    local pid_status=$?
    if ((pid_status != 1)); then
      exit 1
    fi
    echo "${service_name} is not running; no PID file at ${pid_file}."
    return 0
  fi

  if ! is_pid_running "${pid}"; then
    echo "${service_name} is not running; removing stale PID file ${pid_file}."
    rm -f "${pid_file}"
    return 0
  fi

  echo "Stopping ${service_name} with PID ${pid}..."
  kill "${pid}"

  local waited=0
  while is_pid_running "${pid}" && ((waited < 15)); do
    sleep 1
    waited=$((waited + 1))
  done

  if is_pid_running "${pid}"; then
    echo "Error: ${service_name} did not stop after ${waited}s." >&2
    echo "PID file left in place: ${pid_file}" >&2
    exit 1
  fi

  rm -f "${pid_file}"
  echo "${service_name} stopped."
}
