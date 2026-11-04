#!/usr/bin/env bash
# Human-in-the-loop reproduction loop.
# Copy this file and edit the steps below. The user runs the copy in their
# own terminal: the agent's shell has no terminal on stdin, so the script
# stops at once there.
#
# Usage:
#   bash <copy of hitl-loop.template.sh>
#
# Two helpers:
#   step "<instruction>"          → show instruction, wait for Enter
#   capture VAR "<question>"      → show question, read response into VAR
#
# At the end, captured values are printed as KEY=VALUE; the user pastes those
# lines back to the agent.
#
# Every captured value reaches the agent, so capture observations, leave
# signing in to the user as a `step`, and have the user replace any secret
# with <REDACTED> before pasting.

set -euo pipefail

if [ ! -t 0 ]; then
  echo 'hitl-loop: stdin is not a terminal; run this in your own terminal.' >&2
  exit 2
fi

step() {
  printf '\n>>> %s\n' "$1"
  read -r -p "    [Enter when done] " _
}

capture() {
  local var="$1" question="$2" answer
  printf '\n>>> %s\n' "$question"
  read -r -p "    > " answer
  printf -v "$var" '%s' "$answer"
}

# --- edit below ---------------------------------------------------------

step "Open the app at http://localhost:3000 and sign in."

capture ERRORED "Click the 'Export' button. Did it throw an error? (y/n)"

capture ERROR_MSG "Paste the error message (or 'none'):"

# --- edit above ---------------------------------------------------------

printf '\n--- Captured: replace any secret below with <REDACTED> before pasting ---\n'
printf 'ERRORED=%s\n' "$ERRORED"
printf 'ERROR_MSG=%s\n' "$ERROR_MSG"
