#!/usr/bin/env bash
# Capture exactly what the barcode scanner emits, as kernel input events.
#
#   sudo ./capture-scan.sh [seconds]
#
# --grab takes EXCLUSIVE access to the scanner, so scanned data does NOT leak
# into whatever window has focus. Nothing is typed anywhere while this runs.
set -euo pipefail

DEV_LINK=/dev/input/by-id/usb-MINJCODE_MINJCODE_MJ2818A_00000000011C-event-kbd
OUT="${OUT:-scan-capture.log}"
SECS="${1:-120}"

if [[ $EUID -ne 0 ]]; then
  echo "Needs root to read /dev/input. Re-run: sudo $0 $SECS" >&2; exit 1
fi
if [[ ! -e $DEV_LINK ]]; then
  echo "Scanner not found at:" >&2; echo "  $DEV_LINK" >&2
  echo "Plugged in? Check: ls -l /dev/input/by-id/ | grep -i minj" >&2; exit 1
fi

echo "Capturing from $(readlink -f "$DEV_LINK") for ${SECS}s -> $OUT"
echo "Scan the sheet in numbered order, pausing ~2s between barcodes."
echo "Input is grabbed: nothing will be typed into your desktop."
echo
timeout "$SECS" evtest --grab "$DEV_LINK" > "$OUT" 2>&1 || true
chown --reference=. "$OUT" 2>/dev/null || true
echo
echo "Done. $(grep -c 'type 1 (EV_KEY)' "$OUT" 2>/dev/null || echo 0) key events -> $OUT"
echo "Now run:  ./analyze-scan.py $OUT"
