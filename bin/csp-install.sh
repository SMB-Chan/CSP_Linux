#!/bin/bash
# Installs Clip Studio Paint 5.1.4 into the dedicated Wine prefix.
# The installer itself is never modified; it is only executed.
set -u
. "$HOME/ClipStudio/env.sh"
export WINEDEBUG="${WINEDEBUG:--all}"

SETUP="${CSP_SETUP:-/home/intel/デスクトップ/clip/CSP_514w_setup.exe}"
LOG="$CSP_HOME/logs/install.log"
mkdir -p "$(dirname "$LOG")"

case "${1:-gui}" in
  silent)
    echo "[csp] silent install: $SETUP"
    wine "$SETUP" /s /v"/qn" 2>&1 | tee "$LOG"
    echo "exit=${PIPESTATUS[0]}" | tee -a "$LOG"
    ;;
  gui|"")
    echo "[csp] interactive install: $SETUP"
    wine "$SETUP" 2>&1 | tee "$LOG"
    echo "exit=${PIPESTATUS[0]}" | tee -a "$LOG"
    ;;
  *)
    echo "usage: csp-install.sh [silent|gui]" >&2
    exit 2
    ;;
esac
