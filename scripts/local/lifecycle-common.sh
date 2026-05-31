#!/usr/bin/env bash

source_env_file() {
  local env_file="$1"

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

    if [[ "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ && -z "${!key+x}" ]]; then
      set -a
      eval "${line}"
      set +a
    fi
  done <"${env_file}"
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
    pid="$(cat "${pid_file}")"
    if [[ "${pid}" =~ ^[0-9]+$ ]]; then
      echo "${pid}"
      return 0
    fi
  fi

  return 1
}

is_pid_running() {
  local pid="$1"

  kill -0 "${pid}" >/dev/null 2>&1
}

start_managed_service() {
  local service_name="$1"
  local pid_file="$2"
  local log_file="$3"
  shift 3

  mkdir -p "$(dirname "${pid_file}")" "$(dirname "${log_file}")"

  local existing_pid
  if existing_pid="$(read_pid_file "${pid_file}")" && is_pid_running "${existing_pid}"; then
    echo "${service_name} is already running with PID ${existing_pid}."
    echo "Log: ${log_file}"
    return 0
  fi

  rm -f "${pid_file}"

  echo "Starting ${service_name}..."
  echo "Log: ${log_file}"
  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] starting ${service_name}: $*" >>"${log_file}"
  nohup "$@" >>"${log_file}" 2>&1 &

  local pid="$!"
  echo "${pid}" >"${pid_file}"

  sleep 1

  if is_pid_running "${pid}"; then
    echo "${service_name} started with PID ${pid}."
    echo "PID file: ${pid_file}"
    return 0
  fi

  echo "Error: ${service_name} exited during startup." >&2
  echo "Last log lines:" >&2
  tail -n 40 "${log_file}" >&2 || true
  rm -f "${pid_file}"
  exit 1
}

stop_managed_service() {
  local service_name="$1"
  local pid_file="$2"

  local pid
  if ! pid="$(read_pid_file "${pid_file}")"; then
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
