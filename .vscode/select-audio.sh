#!/usr/bin/env bash
set -euo pipefail
cd "${1:-$(pwd)}"

shopt -s nullglob
files=(audio/*.{m4a,wav,mp3})

if [[ ${#files[@]} -eq 0 ]]; then
  echo "No audio files found in audio/." >&2
  exit 1
fi

choices=()
for f in "${files[@]}"; do
  choices+=("$(basename "$f")")
done

selection=$(osascript <<EOF
set choices to {$(printf '"%s",' "${choices[@]}" | sed 's/,$//')}
set chosen to choose from list choices with prompt "Select audio file to transcribe:"
if chosen is false then
  return ""
else
  return item 1 of chosen
end if
EOF
)

if [[ -z "$selection" ]]; then
  echo "No file selected." >&2
  exit 1
fi

make transcribe FILE="audio/$selection"
