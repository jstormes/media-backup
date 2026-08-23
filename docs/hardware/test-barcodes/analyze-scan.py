#!/usr/bin/env python3
"""Segment an evtest capture into per-barcode scans and report the keys emitted.

    ./analyze-scan.py scan-capture.log [--gap 1.0]

Scans are separated by pauses; any gap larger than --gap starts a new scan.
Reports each scan's decoded text plus any non-character keys (F1-F12, Tab,
Enter, ...) which is the whole point of the exercise.
"""
import re, sys, argparse

EV = re.compile(r'time (\d+\.\d+).*type 1 \(EV_KEY\), code \d+ \(([A-Z0-9_]+)\), value (\d)')

SHIFTS = {'KEY_LEFTSHIFT', 'KEY_RIGHTSHIFT'}
PLAIN = {f'KEY_{c}': c.lower() for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'}
PLAIN |= {f'KEY_{d}': d for d in '0123456789'}
PLAIN |= {'KEY_MINUS': '-', 'KEY_DOT': '.', 'KEY_SLASH': '/', 'KEY_SPACE': ' ',
          'KEY_EQUAL': '=', 'KEY_COMMA': ','}
SHIFTED = {'KEY_MINUS': '_', 'KEY_SLASH': '?', 'KEY_EQUAL': '+', 'KEY_COMMA': '<',
           'KEY_DOT': '>'}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('log'); ap.add_argument('--gap', type=float, default=1.0)
    a = ap.parse_args()

    events = []
    for line in open(a.log, errors='replace'):
        m = EV.search(line)
        if m:
            events.append((float(m.group(1)), m.group(2), int(m.group(3))))
    if not events:
        print('No EV_KEY events found. Was the scanner grabbed correctly?')
        return 1

    # segment on gaps
    scans, cur, last = [], [], None
    for t, key, val in events:
        if last is not None and t - last > a.gap:
            scans.append(cur); cur = []
        cur.append((t, key, val)); last = t
    if cur: scans.append(cur)

    print(f'{len(events)} key events -> {len(scans)} scans '
          f'(gap threshold {a.gap}s)\n')
    for i, sc in enumerate(scans, 1):
        shift = False; text = []; special = []
        for t, key, val in sc:
            if key in SHIFTS:
                shift = (val != 0); continue
            if val != 1:            # keydown only
                continue
            if key in PLAIN:
                text.append((SHIFTED.get(key, PLAIN[key].upper()) if shift
                             else PLAIN[key]))
            else:
                special.append(key.replace('KEY_', ''))
        dur = sc[-1][0] - sc[0][0]
        print(f'--- scan {i:>2}  ({dur*1000:.0f} ms, {len(sc)} events)')
        if text:    print(f'    text    : {"".join(text)!r}')
        if special: print(f'    SPECIAL : {" ".join(special)}')
        if not text and not special: print('    (no keydown events)')
    print('\nSPECIAL lines are what matter: F1-F12 there means the scanner can')
    print('emit function keys for that barcode. TAB/ENTER/BACKSPACE on the')
    print('cells marked with a warning are expected and prove nothing.')
    return 0

sys.exit(main())
