#!/bin/bash
# Shared WSL/Windows host resolver for Brain tools
# Source this file: . "$TOOLS/lib/wsl-host.sh"
#
# Provides:
#   WSL_HOST_IP  — the IP address of the Windows host from WSL
#   wsl_url()    — builds a URL for a Windows-hosted service
#
# Usage:
#   . "$TOOLS/lib/wsl-host.sh"
#   curl "$(wsl_url 8800)/api/health"    # → http://172.x.x.1:8800/api/health
#   curl "$(wsl_url 8798)/status"        # → http://172.x.x.1:8798/status
#
# On Windows (non-WSL), falls back to localhost.

if [[ -f /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
  WSL_HOST_IP=$(ip route show default 2>/dev/null | awk '{print $3}')
  WSL_HOST_IP="${WSL_HOST_IP:-localhost}"
else
  WSL_HOST_IP="localhost"
fi

wsl_url() {
  local port="${1:?Usage: wsl_url <port>}"
  echo "http://${WSL_HOST_IP}:${port}"
}
