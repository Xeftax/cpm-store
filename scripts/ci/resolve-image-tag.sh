#!/usr/bin/env bash
# Resolve a deploy tag: an explicit override, or the caller's own default.
# See .github/actions/deploy/image-tag/action.yml for why the default's *source* is
# deliberately not this script's concern.
#
# A [C] script, not bundled inside the action: read-only, no secrets, no mutation — "what
# tag would my next deploy pick" is a real, low-stakes question worth answering from a
# developer's own checkout, independent of any deploy actually running. That is the
# argument that also makes sast-python.sh/lint-python.sh/typecheck-python.sh [C]. It
# reaches a consumer because nothing excludes it: the manifest is a denylist now,
# so a file travels unless `.dockyardignore` says otherwise.
set -euo pipefail

if [ -n "${OVERRIDE_TAG}" ]; then
  # Always a Docker tag, whatever validate_sha says: the value is written to $GITHUB_OUTPUT,
  # where a newline would forge a line of the step's outputs.
  if [[ ! "${OVERRIDE_TAG}" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
    echo "::error::Invalid override_tag: not a Docker tag ([A-Za-z0-9_][A-Za-z0-9_.-]{0,127})"
    exit 1
  fi
  if [ "${VALIDATE_SHA}" = "true" ] && [[ ! "${OVERRIDE_TAG}" =~ ^[0-9a-f]{40}$ ]]; then
    echo "::error::Invalid override_tag: must be a 40-character git SHA (got: ${OVERRIDE_TAG})"
    exit 1
  fi
  echo "tag=${OVERRIDE_TAG}" >> "${GITHUB_OUTPUT}"
  echo "needs_build=false" >> "${GITHUB_OUTPUT}"
  echo "Using explicit override: ${OVERRIDE_TAG} (skipping build)"
else
  if [ -z "${DEFAULT_TAG}" ]; then
    echo "::error::No override_tag given and default_tag is empty — the caller must compute one."
    exit 1
  fi
  if [[ ! "${DEFAULT_TAG}" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
    echo "::error::Invalid default_tag: not a Docker tag ([A-Za-z0-9_][A-Za-z0-9_.-]{0,127})"
    exit 1
  fi
  echo "tag=${DEFAULT_TAG}" >> "${GITHUB_OUTPUT}"
  echo "needs_build=true" >> "${GITHUB_OUTPUT}"
  echo "Using default: ${DEFAULT_TAG} (build required)"
fi
