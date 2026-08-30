# Media Backup Capture Application — Build Spec

**For:** AI agent implementation — this document is the single source of truth.
**Source:** `PLAN.md` (wayfinder map, `#1`).
**Version:** 1.0 — 2026-08-29

---

## 1. Overview

A desktop application for backing up DVDs and BluRays to local storage. The user interacts almost entirely through a USB barcode scanner (HID keyboard-wedge). Each barcode prints a single function-key code — F1 through F6 — encoded as an ASCII control character inside a Code 128 barcode.

The application manages **collections** (a TV season or movie boxset), tracks the **disks** within each collection, and calls **MakeMKV** to copy the physical disc to disk. Up to 16 optical drives may be attached; the system supports multiple active collections simultaneously.

### Stack

| Layer | Technology |
|---|---|
| Framework | **Tauri v2** — monolithic, single binary |
| Backend | **Rust** (Tauri command handlers, event emitters) |
| Frontend | **Svelte** (single-page, runs inside Tauri WebView) |
| Disc copying | **MakeMKV v1.18+** — pre-installed on target, not bundled |
| Barcode scanner | HID keyboard-wedge — F1–F10 via ASCII control bytes 0x16–0x1F |
| Persistence | File-based JSON on disk |
| Drive detection | netlink udev monitor + sysfs polling fallback |
| Config | `~/.config/media-backup/drives.json` |

### Non-goals

- Streaming / network transfer — disc copies go to local disk.
- DVD ripping — only full-disc backup (`backup` command), no single-title remux.
- Cloud / archive integration — finished collections are later moved manually.
- Web version — this is a native desktop app only.

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Svelte Frontend                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │Collection│ │Collection│ │Collection│ │ Finished│ │
│  │  Card #1 │ │  Card #2 │ │  Card #N │ │  Tab    │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────────┘ │
│       │             │            │                    │
│  ┌────┴─────────────┴────────────┴────────────────┐  │
│  │              Keyboard Event Listener            │  │
│  │  (F1=New, F2=UPC, F3=AddDrive, F4=Delete,      │  │
│  │   F5=Done, F6=DeleteCollection)                 │  │
│  └───────────────────┬───────────────────────────┘  │
│                      │ Tauri IPC                     │
├──────────────────────┼───────────────────────────────┤
│              Tauri Backend (Rust)                     │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │
│  │CollectionMgr │ │DiskMgr       │ │ UdevMonitor  │ │
│  │(JSON CRUD)   │ │(status,      │ │+ sysfs poller│ │
│  │              │ │  title)      │ │              │ │
│  └──────────────┘ └──────────────┘ └──────┬───────┘ │
│  ┌──────────────┐ ┌──────────────┐         │        │
│  │MakeMKV       │ │DriveMapper   │         │        │
│  │(process mgr) │ │(config +     │         │        │
│  │              │ │  resolve)    │         │        │
│  └──────────────┘ └──────────────┘         │        │
│  ┌──────────────┐                          │        │
│  │StoragePaths  │◄─────────────────────────┘        │
│  │(in-progress/  │                                  │
│  │ finished/     │                                  │
│  │ deleted/)     │                                  │
│  └──────────────┘                                  │
└─────────────────────────────────────────────────────┘
```

### Key design decisions

- **Single-process backend.** No separate daemon — Tauri spawns and manages all subprocesses (MakeMKV, drive-mapper).
- **No database.** Each collection and its disks are stored as small JSON files on disk. This is simple and survives crashes.
- **File-system-based state machine.** Collections live in `in-progress/`, move to `finished/` when complete, or `deleted/` when abandoned.
- **MakeMKV is a process, not a library.** Every integration path spawns a process and parses stdout. There is no FFI or shared library to link.
- **Context-mode keyboard input.** The app enters a named mode (IDLE, UPC, ADD_DRIVE, DELETE, etc.) when an F-key is scanned, stays in that mode for 10 seconds, and times out back to IDLE if nothing else happens.

---

## 3. Data Models

### 3.1 `collection.json`

Location: `<storage-path>/in-progress/<uuid>/collection.json` (or `finished/` / `deleted/`)

```jsonc
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",  // UUID v4
  "upc": null,                                      // null | string (12 digits)
  "status": "active",                               // "active" | "done" | "deleted"
  "disks": ["disk-1.json", "disk-2.json"],          // ordered list of disk file names
  "created_at": "2026-08-29T14:30:00Z",             // ISO 8601, UTC
  "completed_at": null,                             // ISO 8601, UTC | null
  "deleted_at": null,                               // ISO 8601, UTC | null
  "storage_path": "/mnt/storage/collections/"       // base path for this collection
}
```

### 3.2 `disk-N.json`

Location: `<storage-path>/in-progress/<uuid>/<uuid>/disk-1.json` (or `disk-2.json`, etc.)
Each disk gets its own sub-directory under the collection directory.

```jsonc
{
  "disk_number": 1,                                   // u32, 1-based
  "season": 1,                                        // u32, 1-based
  "is_not_applicable": false,                         // true when disk/season = N/A
  "drive_id": "drive-a",                              // string, maps to logical name "Drive-A"
  "status": "waiting",                                // "waiting" | "copying" | "done" | "failed"
  "copy_success": null,                               // null | true | false
  "bytes_copied": null,                               // null | u64
  "output_dir": null,                                 // null | string (full path to BDMV output)
  "title": null,                                      // null | string (title name from MakeMKV scan)
  "error": null,                                      // null | string (last error message)
  "created_at": "2026-08-29T14:30:05Z",               // ISO 8601, UTC
  "updated_at": "2026-08-29T14:30:05Z",               // ISO 8601, UTC
  "copy_started_at": null,                            // ISO 8601, UTC | null
  "copy_completed_at": null                           // ISO 8601, UTC | null
}
```

### 3.3 `drives.json` (config)

Location: `~/.config/media-backup/drives.json`

```jsonc
{
  "drive-a": "/dev/sr0",
  "drive-b": "/dev/sr1",
  "drive-c": "/dev/sr2"
}
```

The key is the logical identifier (lowercase, hyphenated). The value is the OS device node.
The frontend displays the logical name as `Drive-A`, `Drive-B`, etc.

### 3.4 `config.json` (app settings)

Location: `~/.config/media-backup/config.json`

```jsonc
{
  "storage_path": "/mnt/storage/collections/",        // base directory
  "scan_interval_ms": 5000,                           // how often to refresh storage listing
  "context_timeout_ms": 10000                         // how long a barcode context stays active
}
```

---

## 4. State Machines

### 4.1 Collection states

```
               ┌───────┐
               │ active │
               └──┬────┘
                  │
        ┌─────────┴──────────┐
        │                    │
        ▼                    ▼
  ┌──────────┐        ┌──────────┐
  │  done    │        │ deleted  │
  └──────────┘        └──────────┘
```

| Transition | Trigger | Effect |
|---|---|---|
| **create** | System | New collection: status = "active", created_at = now, disks = [], upc = null |
| **set_upc** | F2 → barcode → UUID | Sets `upc`, updated_at = now |
| **add_disk** | F3 → Drive-A scan | Adds a disk entry (status = "waiting") |
| **delete_disk** | F4 → disk barcode | Removes disk from collection, moves disk dir to deleted/ |
| **mark_done** | F5 (Collection Done) | Sets status = "done", completed_at = now |
| **delete** | F6 (Delete Collection) | Sets status = "deleted", deleted_at = now, moves collection dir to deleted/ |

### 4.2 Disk states

```
  waiting ──▶ copying ──▶ done
      │               │
      │               └─▶ failed ◀──┘
      │                    ▲
      └────────────────────┘ (re-tried)
```

| Transition | Trigger | Effect |
|---|---|---|
| **waiting → copying** | Drive tray closes + disc inserted + status == "waiting" | Sets status = "copying", copy_started_at = now, launches MakeMKV `backup` command |
| **copying → done** | MakeMKV exits 0, output directory exists and contains `BDMV/` | Sets status = "done", copy_success = true, copy_completed_at = now |
| **copying → failed** | MakeMKV emits MSG:5010 / unexpected exit / output dir missing | Sets status = "failed", copy_success = false, error = last error message |
| **failed → waiting** | Manual retry (future feature; not required in v1) | Resets copying-related fields, status = "waiting" |

### 4.3 Copy trigger logic

When the app detects a media-inserted event for a drive associated with a `waiting` disk:

1. **Resolve the drive** from the config (`drives.json` → `/dev/srN` → `drive_id`).
2. **Find the disk** entry whose `drive_id` matches and whose `status` == "waiting".
3. **Scan the disc** via `makemkvcon -r --cache=1 --progress=-same info dev:/dev/srN`.
4. **Validate:** `TCOUNT > 0` and no `MSG:5010`. If not, mark disk "failed" with "No usable titles".
5. **Create output directory:** `<storage_path>/in-progress/<collection_uuid>/<disk_uuid>/output`.
6. **Launch backup:** `makemkvcon -r --progress=-same --decrypt --cache=1 backup disc:0 <output_dir>`.
7. **Follow progress:** Parse `PRG*` records on stdout. Emit a Tauri event each time the percentage changes by ≥ 1%.
8. **On completion:** Verify output directory contains `BDMV/` and at least one `.m2ts` file. Set disk status accordingly.

---

## 5. Barcode System

### 5.1 Hardware

The scanner is a USB HID keyboard-wedge (MINJCODE MJ2818A, OEM rebrand of WoneNice WN3300). It types keystrokes into the focused window. There is no separate configuration interface.

### 5.2 Control code → key mapping

| Control byte | Key | App function |
|---|---|---|
| `0x16` | F1 | New Collection |
| `0x17` | F2 | Scan UPC |
| `0x18` | F3 | Add Drive |
| `0x19` | F4 | Delete (disk) |
| `0x1A` | F5 | Collection Done |
| `0x1B` | F6 | Delete Collection |
| `0x1C` | F7 | (reserved) |
| `0x1D` | F8 | (reserved) |
| `0x1E` | F9 | (reserved) |
| `0x1F` | F10 | (reserved) |
| `0x10` | F11 | (reserved) |
| `0x15` | F12 | (reserved) |

F1–F10 = control bytes 0x16–0x1F in order. Formula: `F_n = 0x15 + n` for n ∈ [1,10].

### 5.3 Context mode state machine

```
                    ┌───────────────────────────────────────┐
                    │                                       │
                    │            IDLE                        │
                    │  (waiting for an F-key scan)           │
                    │                                       │
                    └──────┬──────────────┬───────────────┘
                           │              │
               F1 scanned │              │ F2–F10 scanned
                           ▼              ▼
               ┌─────────────────────────────────────────────┐
               │                                             │
               │          NEW_COLLECTION (mode)               │
               │          (waiting for UUID scan)             │
               │                                             │
               └───────┬─────────────────────────────────────┘
                       │ 10s timeout or UUID scan
                       ▼
               ┌─────────────────────────────────────────────┐
               │                                             │
               │               UPC (mode)                     │
               │          (waiting for UPC barcode)           │
               │                                             │
               └───────┬─────────────────────────────────────┘
                       │ 10s timeout or UPC barcode received
                       ▼
               ┌─────────────────────────────────────────────┐
               │                                             │
               │          ADD_DRIVE (mode)                    │
               │       (waiting for Drive-A/B/C scan)         │
               │                                             │
               └───────┬─────────────────────────────────────┘
                       │ 10s timeout or Drive-A/B/C scan
                       ▼
               ┌─────────────────────────────────────────────┐
               │                                             │
               │        SELECT_DISK (mode)                    │
               │   (waiting for a disk barcode on active card) │
               │                                             │
               └───────┬─────────────────────────────────────┘
                       │ 10s timeout or disk UUID scan
                       ▼
               ┌─────────────────────────────────────────────┐
               │                                             │
               │          DELETE_DISK (mode)                  │
               │       (waiting for Drive-A/B/C scan)         │
               │                                             │
               └───────┬─────────────────────────────────────┘
                       │ 10s timeout or Drive-A/B/C scan
                       ▼
               ┌─────────────────────────────────────────────┐
               │                                             │
               │       COLLECTION_DONE (mode)                 │
               │                                             │
               └───────┬─────────────────────────────────────┘
                       │ 10s timeout or confirmed
                       ▼
               ┌─────────────────────────────────────────────┐
               │                                             │
               │     DELETE_COLLECTION (mode)                 │
               │                                             │
               └───────┬─────────────────────────────────────┘
                       │ 10s timeout or confirmed
                       ▼
               ┌─────────────────────────────────────────────┐
               │                                             │
               │                IDLE ←───────────────────────┘
               │          (loop back)                         │
               │                                             │
               └─────────────────────────────────────────────┘
```

#### Rules

1. **One mode at a time.** Scanning an F-key while in a mode enters that new mode (preempting the old one). The 10-second timeout resets.
2. **10-second timeout.** After scanning an F-key, the app stays in that mode for 10 seconds. If no data barcode is scanned in that window, it returns to IDLE.
3. **Status indicator.** The top of the UI always shows the current mode: `IDLE`, `NEW_COLLECTION`, `UPC`, `ADD_DRIVE`, `SELECT_DISK`, `DELETE_DISK`, `COLLECTION_DONE`, or `DELETE_COLLECTION`.
4. **Mode barcodes are indistinguishable from data barcodes at the OS level.** Both are just keystrokes. The mode determines how a subsequent data barcode is interpreted.
5. **No terminator.** The scanner does not append Enter or Tab. The app determines scan completion by idle timeout (~200 ms between characters).

### 5.4 UPC scan

- UPC-A barcodes are 12 digits (0–9).
- When the app is in UPC mode, it buffers incoming keystrokes until a 200 ms idle gap.
- If the buffered string is exactly 12 digits, it is accepted as the UPC.
- If not (e.g., a non-UPC barcode was scanned), the app shows a warning beep and returns to IDLE.
- Scanning a UPC while the collection already has one updates it (no confirmation required; shows a "replaced" toast).
- Duplicate UPC: warn with a toast ("Collection X already has this UPC — continuing") but allow.

### 5.5 Drive scan (F3 → ADD_DRIVE mode)

1. User scans F3 (Add Drive). App enters ADD_DRIVE mode.
2. User scans a Drive-A / Drive-B / Drive-C barcode (encoded as the text "DRIVE-A", "DRIVE-B", etc. — printable characters, not control codes).
3. App resolves the drive path from `drives.json`.
4. If the drive is not in the config, show an error: "Drive not configured."
5. If the drive is configured and a collection is active, add a disk entry (status = "waiting") and enter SELECT_DISK mode.

### 5.6 Select disk (disk number / season)

1. User scans a Drive-A barcode to associate the physical drive with the disk.
2. App shows a prompt for disk number and season.
3. **Default values:** disk_number = auto-increment (first disk = 1, second = 2, etc.), season = 1.
4. **Persisting season:** once the user sets a season > 1, it becomes the default for all future disks in this collection.
5. **N/A toggle:** a "Not Applicable" toggle sets `is_not_applicable = true`, which suppresses the disk/season prompt.
6. After confirming, the disk entry is created and the UI shows a "Copy" button for the disk (or the copy is triggered automatically when media is inserted).

### 5.7 Delete disk (F4 → SELECT_DISK mode)

1. User scans F4 (Delete). App enters SELECT_DISK mode.
2. User scans a disk's barcode (the UUID displayed on the disk card).
3. App removes the disk from the collection and moves its directory to `deleted/`.

### 5.8 Collection Done (F5)

1. User scans F5. App enters COLLECTION_DONE mode.
2. If the collection has no UPC, show a warning toast. (This is not a blocker.)
3. After 10 seconds (or immediate confirmation — TBD), set status = "done", completed_at = now.
4. The collection card moves to the "Finished" tab.

### 5.9 Delete Collection (F6)

1. User scans F6. App enters DELETE_COLLECTION mode.
2. After 10 seconds (or immediate confirmation — TBD), set status = "deleted", deleted_at = now, and move the entire collection directory to `deleted/`.

---

## 6. Drive Mapping

### 6.1 Config file

`~/.config/media-backup/drives.json`:

```json
{
  "drive-a": "/dev/sr0",
  "drive-b": "/dev/sr1",
  "drive-c": "/dev/sr2"
}
```

### 6.2 Discovery (first run)

On first run, if `drives.json` does not exist, the app:

1. Runs `makemkvcon -r --cache=1 info disc:9999` to enumerate drives.
2. Filters for drives with `state == 2` (disc inserted).
3. Presents the list to the user: `Drive-A: HL-DT-ST BD-RE BU40N (/dev/sr0)`, etc.
4. User assigns each detected drive to a logical name (A, B, C…).
5. App writes `drives.json` and saves it.

If no drives have discs inserted, the user can manually enter device paths.

### 6.3 Runtime resolution

Given a `/dev/srN` path (from udev event or MakeMKV enumeration), the backend:

```rust
fn resolve_drive_id(&self, device_path: &str) -> Option<String> {
    for (logical, path) in &self.config.drives {
        if path == device_path {
            return Some(logical.clone());
        }
    }
    None
}
```

The frontend displays logical names as `Drive-A`, `Drive-B`, etc. (capitalize and hyphenate the key).

---

## 7. MakeMKV Integration

### 7.1 Overview

MakeMKV is a pre-installed system dependency (`/usr/local/bin/makemkvcon`). It is never bundled or redistributed. The app spawns `makemkvcon` as a child process and communicates entirely through its robot-mode stdout.

### 7.2 Critical rules (from research)

1. **Exit code 0 is NOT a success signal.** Operational failures (no disc, no titles) return 0. Parse output records, not exit codes.
2. **`--cache=1` is required.** Without it, MakeMKV performs full-device reads on every scan, which is extremely slow.
3. **Progress max is 65536, not 100.** `PRGV:current,total,65536` — percentage = `value * 100.0 / 65536.0`.
4. **`backup` requires `disc:` source, not `dev:`.** Using `dev:` fails with `"Backup source must start with disc:"`.
5. **`backup --progress=-same` interleaves `PRG*` records with `MSG` records on stdout.** Use this.
6. **`--decrypt` is needed for Blu-ray.** Not needed for DVD (no encryption).
7. **Always use `-r` (robot mode).** Non-robot output is prose, not parseable records.

### 7.3 Drive enumeration

```bash
makemkvcon -r --cache=1 info disc:9999
```

This emits exactly 16 `DRV` lines (slots 0–15), then `MSG:5010 Failed to open disc`, then exits 0. Parse the `DRV` lines to discover all drives.

**DRV record format:**

```
DRV:index,state,flags,unused,"drive_name","disc_name","device_path"
```

| State | Meaning |
|---|---|
| 0 | Empty, tray closed |
| 1 | Empty, tray open |
| 2 | Disc inserted (ready) |
| 3 | Loading |
| 256 | No drive |
| 257 | Unmounting |

### 7.4 Disc scan

```bash
makemkvcon -r --progress=-same --cache=1 info dev:/dev/sr0
```

Or by MakeMKV index:

```bash
makemkvcon -r --progress=-same --cache=1 info disc:0
```

**Success criteria:** `TCOUNT > 0` and no `MSG:5010` on the target source.

**Output records of interest:**

| Prefix | Meaning |
|---|---|
| `MSG:1005` | Engine started (always first — wait for this before parsing) |
| `MSG:5010` | Failed to open disc — failure signal |
| `CINFO:1,...` | Disc type (6209 = Blu-ray, 6201 = DVD) |
| `CINFO:2,...` | Disc name |
| `TCOUNT:n` | Total usable titles (n > 0 = success) |
| `TINFO:0,2,...` | Title name |
| `TINFO:0,9,...` | Title duration (H:MM:SS) |
| `TINFO:0,11,...` | Title exact bytes (use for arithmetic, not TINFO:10) |
| `SINFO:0,0,1,6201,"Video"` | Stream type |
| `SINFO:0,0,5,0,"V_MPEG4/ISO/AVC"` | Codec |
| `SINFO:0,0,19,0,"1920x1080"` | Resolution |

### 7.5 Full disc backup

```bash
makemkvcon -r --progress=-same --decrypt --cache=1 backup disc:0 /path/to/output
```

**Notes:**
- Source **must** be `disc:` for `backup`. The drive index `0` refers to the first drive in the MakeMKV slot table.
- For DVD, omit `--decrypt` (DVDs without CSS are unencrypted; MakeMKV handles this transparently — but if you want to be explicit, the flag is safe to always pass).
- The process emits `PRGT` (job name), `PRGC` (sub-step name), and `PRGV` (progress values) on stdout.

**Progress parsing:**

```rust
// PRGV:current,total,max
// current and total are both on the same record
// pct(current) and pct(total) are separate views of progress
fn parse_progress(line: &str) -> Option<(f64, f64)> {
    // line = "PRGV:current,total,max"
    let parts: Vec<u64> = line
        .trim_start_matches("PRGV:")
        .split(',')
        .filter_map(|s| s.parse().ok())
        .collect();
    if let [cur, tot, max] = parts[..] {
        let pct = |x: u64| x as f64 * 100.0 / max as f64;
        Some((pct(cur), pct(tot)))
    } else {
        None
    }
}
```

**Completion criteria:**
- Process exits 0 (or — more reliably — the last `PRGV` record has `total == max`).
- Output directory exists and contains a `BDMV/` directory with at least one `.m2ts` file.
- No `MSG:5010` or similar error messages in the output stream.

### 7.6 Process management

The backend manages MakeMKV processes as follows:

```rust
struct MakeMkvProcess {
    child: std::process::Child,
    reader: BufReader<ChildStdout>,
    title: String,
    drive_index: u32,
}
```

- Spawn with `stdout = Stdio::piped()` and `stdin = Stdio::null()`.
- Read stdout with `BufReader::lines()`.
- On each line, dispatch to the appropriate handler (`PRGV` → emit progress event, `MSG` → log/check for errors, `TCOUNT` → success gate).
- On completion (process exits), emit a final status event to the frontend.
- On error (process killed, pipe broken), emit a failure event.

**Important: concurrent drives.** Two `makemkvcon` processes can target two different drives simultaneously without interference. This was confirmed by the MakeMKV architecture (each process opens the drive device independently).

### 7.7 Error handling

| Situation | Signal | Action |
|---|---|---|
| No disc in drive | `MSG:5010` + `TCOUNT:0` | Mark disk "failed", message: "No disc" |
| Drive not responding | Process dies, no PRG* completion | Mark disk "failed", message: "Drive disconnected" |
| Output dir missing after backup | No `BDMV/` in output | Mark disk "failed", message: "Copy produced no output" |
| Process killed by OOM / SIGKILL | `SIGKILL` in wait status | Mark disk "failed", message: "Process killed" |
| Unknown MSG code | Unrecognized code | Log as warning, continue processing |

---

## 8. Storage Layout

### 8.1 Base paths

Three directories under the configured `storage_path` (from `config.json`):

```
<mnt>/collections/
├── in-progress/
│   └── <uuid>/
│       ├── collection.json
│       └── <disk-uuid>/
│           ├── disk-1.json
│           └── output/
│               ├── BDMV/
│               │   ├── BDMV/
│               │   └── ...
│               ├── AACS/
│               └── CERTIFICATE/
├── finished/
│   └── <uuid>/
│       ├── collection.json
│       └── <disk-uuid>/
│           ├── disk-1.json
│           └── output/
│               └── ... (same structure as in-progress)
└── deleted/
    └── <uuid>/
        ├── collection.json
        └── ...
```

### 8.2 Lifecycle

| Action | Collection movement | Disk movement |
|---|---|---|
| Create | `in-progress/<uuid>/` | Disk sub-dirs under collection |
| Copy success | Stays in `in-progress/` until collection done | Stays under collection |
| Collection done | Move to `finished/<uuid>/` | Stays under collection |
| Collection deleted | Move to `deleted/<uuid>/` | Stays under collection (or move to deleted/ — TBD) |
| Disk deleted | Stays | Move disk dir to `<storage_path>/deleted/disk-<uuid>/` |
| Disk copy failed | Stays in `in-progress/` | Stays under collection |

### 8.3 File system polling

The frontend polls for new collections every 5 seconds (configurable in `config.json`). On each poll:

1. Walk `in-progress/` and list UUID subdirectories.
2. Walk `finished/` and list UUID subdirectories.
3. Read `collection.json` from each directory.
4. Read all `disk-N.json` from each collection.
5. Compare against current state — add new, update changed, remove deleted (not found on disk).

This ensures the UI stays in sync even across app restarts or crashes.

---

## 9. UI Component Tree

### 9.1 Layout

```
App
├── StatusBar (always visible)
│   ├── Mode indicator: "IDLE", "UPC", "ADD_DRIVE", etc.
│   ├── Drive status icons (one per drive: ● disc / ○ empty)
│   └── Clock / status
├── TabBar
│   ├── In Progress (active tab by default)
│   └── Finished
├── CollectionCards (scrollable, one column, up to 3 visible)
│   └── CollectionCard (for each active collection)
│       ├── Header: UPC + drive icons + actions
│       ├── Disks list
│       │   └── DiskCard (for each disk)
│       │       ├── Title + disk/season + status badge
│       │       ├── Progress bar (when copying)
│       │       └── Delete button (F4 barcode)
│       └── Footer: "Collection Done" button / "Delete" button
└── ToastContainer (overlays)
    └── Toast messages (non-blocking notifications)
```

### 9.2 Component specifications

#### `StatusBar`
- Shows current mode with color coding:
  - IDLE: neutral (gray)
  - UPC / ADD_DRIVE / SELECT_DISK / DELETE_DISK: active (blue)
  - COLLECTION_DONE / DELETE_COLLECTION: warning (amber)
  - ERROR: error (red)
- Shows drive status dots for each configured drive:
  - Filled circle = disc inserted
  - Empty circle = no disc
- Dots are updated by the udev monitor (or MakeMKV enumeration).

#### `CollectionCard`
- Bordered container with the collection's title area.
- **Header:**
  - UPC barcode display (if set) + barcode for re-scanning
  - Active drive dots
  - "Delete Collection" button (F6)
- **Body:** list of `DiskCard` entries.
- **Footer:**
  - "Collection Done" button (F5)
  - Visible only when status == "active"

#### `DiskCard`
- Shows disk number, season, drive name, status.
- When status = "copying":
  - Animated progress bar
  - Current MakeMKV sub-step name (from `PRGC`)
  - Percentage
- When status = "failed":
  - Red status badge
  - Error message (truncated to 2 lines)
  - Retries button (future)
- When status = "done":
  - Green checkmark badge
  - Title, size, duration from MakeMKV scan
  - Move to top of list (done disks float to top)
- When status = "waiting":
  - Gray "waiting" badge
  - Copy starts automatically when media is inserted

#### `TabBar`
- Two tabs: "In Progress" and "Finished".
- Active tab is underlined/highlighted.
- "Finished" tab shows collections with status = "done" that are still on disk.

#### `ToastContainer`
- Positioned at bottom-center of the screen.
- Each toast auto-dismisses after 5 seconds.
- Overlapping toasts stack upward.
- Types: info (blue), success (green), warning (amber), error (red).

### 9.3 Frontend framework details

- **Svelte 5** (runes mode: `state`, `derived`, `effect`).
- Single file: `src/App.svelte` is the root.
- Use Tauri's `window.onEvent` for backend events (progress, drive status, etc.).
- Use Tauri's `invoke` for command calls (create collection, set UPC, etc.).
- CSS: minimal, system font stack, high-contrast mode for barcode readability.

---

## 10. Tauri API Contract

### 10.1 Commands (Frontend → Backend)

Each command returns a `Result<JsonValue, AppError>`.

| Command | Arguments | Returns | Description |
|---|---|---|---|
| `create_collection` | `{}` | `{ id: string, path: string }` | Create a new active collection, return its UUID and disk path |
| `set_upc` | `{ collection_id: string, upc: string }` | `{ ok: boolean }` | Set the UPC for a collection |
| `add_disk` | `{ collection_id: string, drive_id: string }` | `{ disk_id: string, disk_number: number }` | Add a disk entry, auto-increment disk number |
| `delete_disk` | `{ collection_id: string, disk_id: string }` | `{ ok: boolean }` | Remove a disk from the collection |
| `set_disk_title` | `{ collection_id: string, disk_id: string, title: string }` | `{ ok: boolean }` | Set the title for a disk (from MakeMKV scan) |
| `start_copy` | `{ disk_id: string }` | `{ ok: boolean }` | Start a disc copy (should be auto-triggered, but callable manually) |
| `cancel_copy` | `{ disk_id: string }` | `{ ok: boolean }` | Cancel an in-progress copy (kill MakeMKV process) |
| `complete_collection` | `{ collection_id: string }` | `{ ok: boolean }` | Mark collection as done |
| `delete_collection` | `{ collection_id: string }` | `{ ok: boolean }` | Mark collection as deleted |
| `list_collections` | `{ status: string }` | `{ collections: Collection[] }` | List collections by status (active/done/deleted) |
| `list_drives` | `{}` | `{ drives: DriveInfo[] }` | Enumerate drives via MakeMKV |
| `load_config` | `{}` | `{ config: AppConfig }` | Load app config from disk |
| `save_config` | `{ config: AppConfig }` | `{ ok: boolean }` | Save app config to disk |
| `discover_drives` | `{}` | `{ drives: DiscoveredDrive[] }` | First-run drive discovery (enumerate + prompt for mapping) |

### 10.2 Events (Backend → Frontend)

| Event | Payload | Description |
|---|---|---|
| `collection_updated` | `{ collection_id: string }` | Collection data changed (created, updated, deleted) |
| `disk_updated` | `{ disk_id: string }` | Disk status changed |
| `disk_progress` | `{ disk_id: string, pct: number, substep: string }` | MakeMKV copy progress (emitted when pct changes ≥ 1%) |
| `copy_complete` | `{ disk_id: string, success: boolean }` | Copy finished (success or failure) |
| `drive_status` | `{ drives: DriveStatus[] }` | Drive insertion status changed |
| `error` | `{ message: string }` | User-facing error (toast) |
| `scan_complete` | `{ disk_id: string, title_count: number, title: string }` | Disc scan completed |

### 10.3 Tauri configuration

`src-tauri/tauri.conf.json`:

```json
{
  "productName": "media-backup",
  "version": "0.1.0",
  "identifier": "com.jstormes.media-backup",
  "build": {
    "frontendDist": "../dist",
    "devUrl": "http://localhost:1420"
  },
  "app": {
    "windows": [
      {
        "title": "Media Backup",
        "width": 1024,
        "height": 768,
        "resizable": true
      }
    ],
    "securityCsp": "default-src 'self'; style-src 'self' 'unsafe-inline'"
  },
  "bundle": {
    "active": true,
    "targets": "deb",
    "icon": [
      "icons/32x32.png",
      "icons/128x128.png",
      "icons/128x128@2x.png",
      "icons/icon.icns",
      "icons/icon.ico"
    ]
  }
}
```

---

## 11. Project Structure

```
media-backup/
├── AGENTS.md
├── BUILD-SPEC.md               # ← this file
├── PLAN.md
├── package.json                # project root (dev deps, scripts)
├── tsconfig.json
├── svelte.config.js
├── vite.config.ts
├── src/
│   ├── App.svelte              # root component
│   ├── main.ts                 # entry point
│   ├── lib/
│   │   ├── components/
│   │   │   ├── CollectionCard.svelte
│   │   │   ├── DiskCard.svelte
│   │   │   ├── StatusBar.svelte
│   │   │   ├── TabBar.svelte
│   │   │   ├── Toast.svelte
│   │   │   └── ToastContainer.svelte
│   │   ├── types.ts            # TypeScript type definitions (mirror of Rust types)
│   │   └── events.ts           # Tauri event subscription helpers
│   └── styles/
│       └── app.css             # global styles
├── src-tauri/
│   ├── Cargo.toml              # Rust dependencies
│   ├── tauri.conf.json
│   ├── build.rs
│   ├── capabilities/default.json
│   ├── icons/
│   └── src/
│       ├── main.rs             # Tauri main (window setup, plugins)
│       ├── error.rs            # AppError enum, Result type alias
│       ├── collection.rs       # CollectionMgr (JSON CRUD)
│       ├── disk.rs             # DiskMgr (status, title updates)
│       ├── makemkv.rs          # MakeMkvProcess, spawn/parse/progress
│       ├── udev_monitor.rs     # UdevEventMonitor (netlink + sysfs polling)
│       ├── drive_mapper.rs     # DriveMapper (config load + resolve)
│       ├── storage.rs          # StoragePaths (in-progress/finished/deleted)
│       └── commands/
│           ├── mod.rs          # re-exports all commands
│           ├── collection_cmds.rs
│           ├── disk_cmds.rs
│           ├── copy_cmds.rs
│           ├── config_cmds.rs
│           └── drive_cmds.rs
└── docs/                       # research & reference docs (not part of build)
    ├── makemkv/
    ├── hardware/
    └── agents/
```

### 11.1 Rust dependencies (`Cargo.toml`)

```toml
[dependencies]
tauri = { version = "2", features = [] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
tokio = { version = "1", features = ["full"] }
uuid = { version = "1", features = ["v4", "serde"] }
chrono = { version = "0.4", features = ["serde"] }
notify = "7"                    # filesystem watcher (alternative to polling)
glib = "0.20"                   # for GIO/glib event loop (optional, for udev)
tempfile = "3"

[dev-dependencies]
```

### 11.2 NPM dependencies (`package.json`)

```json
{
  "name": "media-backup",
  "version": "0.1.0",
  "scripts": {
    "dev": "vite dev",
    "build": "vite build",
    "tauri": "tauri",
    "tauri:dev": "tauri dev",
    "tauri:build": "tauri build"
  },
  "devDependencies": {
    "@tauri-apps/cli": "^2",
    "svelte": "^5",
    "svelte-check": "^4",
    "typescript": "^5",
    "vite": "^6"
  },
  "dependencies": {
    "@tauri-apps/api": "^2"
  }
}
```

---

## 12. Build Instructions

### 12.1 Prerequisites

The **build machine** (where the developer builds the app) needs:

1. **Rust toolchain** (stable, via `rustup`)
2. **Node.js 20+** and **npm 9+**
3. **Tauri CLI** (`npm install -g @tauri-apps/cli`)
4. **Desktop dependencies** (Ubuntu 24.04):
   ```bash
   sudo apt update
   sudo apt install -y \
     libgtk-3-dev \
     libwebkit2gtk-4.1-dev \
     librsvg2-dev \
     build-essential \
     curl \
     wget \
     file \
     libssl-dev \
     libayatana-appindicator3-dev
   ```

### 12.2 Building the app

```bash
# Clone the repo
cd media-backup

# Install frontend deps
npm install

# Run in development mode (hot reload)
npm run tauri:dev

# Build for production (deb package)
npm run tauri:build
```

### 12.3 Target system setup

Before installing the app on the target system:

1. **Install MakeMKV** (from source — see `docs/makemkv/README.md`):
   ```bash
   # Build from -oss tarball
   tar xzf makemkv-oss-1.18.3.tar.gz
   cd makemkv-oss-1.18.3
   make -j$(nproc)
   sudo make install
   
   # Build from -bin tarball
   cd ../makemkv-bin-1.18.3
   make -j$(nproc)
   sudo make install
   
   # Add registration key
   makemkvcon reg app_Key="YOUR_KEY_HERE"
   ```

2. **Add user to cdrom group:**
   ```bash
   sudo usermod -aG cdrom $USER
   ```

3. **Install udev rules (automount disabled for optical drives):**
   ```bash
   sudo install -m 0440 udev/90-media-backup-ignore.rules /etc/udev/rules.d/
   sudo udevadm control --reload-rules
   sudo udevadm trigger --subsystem-match=block
   ```

4. **Install the application:**
   ```bash
   sudo dpkg -i target/release/bundle/deb/media-backup_0.1.0_amd64.deb
   ```

5. **Configure drives:**
   - First run will prompt for drive mapping (or create `drives.json` manually).
   - Edit `~/.config/media-backup/drives.json` to add/remove drives.

6. **Set storage path:**
   - Edit `~/.config/media-backup/config.json`:
   ```json
   {
     "storage_path": "/mnt/storage/collections/",
     "scan_interval_ms": 5000,
     "context_timeout_ms": 10000
   }
   ```

---

## 13. Implementation Order

Execute the spec in this order — each phase builds on the previous:

### Phase 1: Skeleton and persistence
1. Set up the Tauri v2 project (Rust backend + Svelte frontend).
2. Implement `StoragePaths` — the three directory structure.
3. Implement `CollectionMgr` — JSON CRUD for collections (read/write `collection.json`).
4. Implement `DiskMgr` — JSON CRUD for disks.
5. Wire up `list_collections` and `create_collection` commands.

### Phase 2: Frontend basics
6. Implement `App.svelte` with the `StatusBar`, `TabBar`, and empty collection lists.
7. Implement `CollectionCard` (static data, no interactivity yet).
8. Implement filesystem polling — walk `in-progress/` and `finished/` every 5 seconds.
9. Make the UI reflect the actual on-disk state.

### Phase 3: Barcode input
10. Implement the keyboard event listener in the frontend.
11. Map F1–F6 keydown events to context modes.
12. Implement the 10-second context timeout.
13. Implement UPC scanning (buffer keystrokes, 200 ms idle timeout, validate 12 digits).
14. Wire `set_upc` command.
15. Implement drive scan (F3 → ADD_DRIVE mode → resolve from config).
16. Implement disk deletion (F4 → SELECT_DISK mode).
17. Implement collection done (F5) and delete (F6).

### Phase 4: MakeMKV integration
18. Implement the `makemkvcon` process launcher in Rust.
19. Implement robot-mode stdout parser (dispatch to MSG / DRV / TCOUNT / PRG handlers).
20. Implement drive enumeration (`info disc:9999` → parse DRV lines).
21. Implement disc scan (`info dev:/dev/sr0` → parse CINFO/TINFO/SINFO/TCOUNT).
22. Implement `backup` command with progress parsing (PRGV → percentage → emit event).
23. Implement copy trigger: when udev event says media inserted → scan → verify → backup.

### Phase 5: Drive detection and automation
24. Implement the udev monitor (netlink → sysfs polling fallback).
25. Implement `DriveMapper` — load config, resolve device path to logical name.
26. Wire drive status dots in the StatusBar (reflects actual drive state).
27. Auto-start copy when media is inserted for a `waiting` disk.

### Phase 6: Polish
28. Error handling: all error paths, toast notifications, retry display.
29. Duplicate UPC warning.
30. Crash recovery: on startup, scan `in-progress/` for disks with status "copying" → mark "failed".
31. UUID display: show first 8 chars of UUID on cards, full UUID in tooltip.
32. Done disks float to top of list.
33. Finished tab: show collections moved to `finished/`.
34. Testing: run the test suite from `docs/makemkv/test-suite.md` against the integrated app.

---

## 14. Testing Checklist

Before considering the spec implementation complete, verify:

### MakeMKV integration
- [ ] `makemkvcon -r --cache=1 info disc:9999` — lists ≥ 16 drives, at least one with `state=2`
- [ ] `makemkvcon -r --cache=1 info dev:/dev/sr0` — `TCOUNT > 0`, emits `TINFO` and `SINFO` records
- [ ] `makemkvcon -r --cache=1 mkv disc:0 0 /tmp/test` — produces an `.mkv` file
- [ ] `makemkvcon -r --progress=-same backup disc:0 /tmp/test` — emits `PRGV` records, exits 0
- [ ] `makemkvcon -r --cache=1 info disc:99` — `MSG:5010` + `TCOUNT:0`, exit 0
- [ ] `makemkvcon -r backup dev:/dev/sr0 /tmp/test` — fails with `"Backup source must start with disc:"`
- [ ] `makemkvcon -r badcmd` — exit 1
- [ ] Two concurrent `makemkvcon` processes on different drives — both succeed

### Application
- [ ] Create a collection, scan a UPC, verify it appears in the card header
- [ ] Add a disk (F3 → Drive-A → confirm), verify disk card appears with "waiting" status
- [ ] Insert disc → copy starts automatically → progress bar animates → status goes to "done"
- [ ] Copy fails (no disc) → status goes to "failed" with error message
- [ ] Delete disk (F4 → select disk) → disk removed from list
- [ ] Collection done (F5) → card moves to "Finished" tab
- [ ] Delete collection (F6) → collection removed from "In Progress", moved to deleted/
- [ ] App restart → state recovered from disk
- [ ] Two collections active simultaneously
- [ ] F-key barcodes on physical printout work end-to-end

---

## Appendix A: MakeMKV attribute IDs

See `docs/makemkv/attribute-ids.md` for the full enum. Quick reference:

| ID | Constant | Meaning |
|---|---|---|
| 1 | `ap_iaDiscType` | Disc type code |
| 2 | `ap_iaName` | Name (disc or title) |
| 8 | `ap_iaChapterCount` | Chapter count |
| 9 | `ap_iaDuration` | Duration H:MM:SS |
| 10 | `ap_iaDiskSize` | Display string (e.g. "29.3 GB") — do not parse |
| 11 | `ap_iaDiskSizeBytes` | Exact bytes — use for arithmetic |
| 16 | `ap_iaSourceFileName` | Source file (e.g. "00001.mpls") |
| 19 | `ap_iaVideoSize` | Resolution (e.g. "1920x1080") |
| 21 | `ap_iaVideoFrameRate` | Frame rate (e.g. "23.976") |
| 27 | `ap_iaOutputFileName` | Suggested output name |
| 28 | `ap_iaLanguage` | Language code (e.g. "eng") |

Drive state codes: 0 = empty closed, 1 = empty open, 2 = disc inserted, 3 = loading, 256 = no drive, 257 = unmounting.

---

## Appendix B: Barcode generation reference

Use `zint` with Code 128 for control-code barcodes:

```bash
# F1 (0x16)
zint --barcode=20 --esc -d '\x16' --scale=2 --height=18 --quietzones --notext -o F1.svg

# F_n: use hex 0x15 + n
# F2 = 0x17, F3 = 0x18, ..., F10 = 0x1F
# F11 = 0x10, F12 = 0x15
```

For printable barcodes (drive names like "Drive-A"):
```bash
# Just encode the text normally
zint --barcode=20 -d 'DRIVE-A' --scale=2 --height=18 --quietzones --notext -o Drive-A.svg
```

**Always verify generated barcodes with a decoder:**
```bash
zbarimg --quiet page-1.png
```
