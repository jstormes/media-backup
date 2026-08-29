# Media Backup — Wayfinder Plan

## Destination

A detailed technical build spec for the Media Backup Capture Application — written for an AI agent to implement.

**Map issue:** [#1](https://github.com/jstormes/media-backup/issues/1) (label `wayfinder:map`)

## Stack

- **Tauri v2** — monolithic, single binary
- **Rust** backend
- **Svelte** frontend
- **HID keyboard-wedge** barcode scanner (F1–F6 keycodes)
- **MakeMKV** — pre-installed on target system
- **File-based JSON** persistence

## Design Decisions (all confirmed in grilling session)

| Area | Decision |
|------|----------|
| Destination | Build spec (Markdown, for AI agent) |
| Stack | Tauri v2 + Rust + Svelte |
| Barcode scanner | Single HID keyboard wedge, F1–F6 keycodes |
| Barcode mapping | Hardcoded (F5 = scan UPC, etc.) |
| Drive mapping | CLI tool (`drive-mapper`) + config file |
| Storage paths | `in-progress/`, `finished/`, `deleted/` |
| Copy trigger | Drive tray close (udev event), no button |
| Progress | Percentage complete |
| Disk/season logic | Per-collection: auto-increment disk, persistent season |
| Errors | Fail fast, inline display |
| Partial copies | Record `copy_success`, `bytes_copied`, `output_dir` |
| Context mode | IDLE/UPC/ADD_DRIVE/DELETE with 10s timeout + status indicator |
| Persistence | File-based JSON |
| Crash recovery | Copying disks → `failed` on restart |
| UUID display | First 8 chars + tooltip |
| Duplicate UPC | Warn but allow |
| UI layout | Flexible, pragmatic component tree |
| Polling | Every 5s for storage path changes |
| Manual collections | Only through the app |

## Data Models (confirmed)

### collection.json
```json
{
  "id": "uuid",
  "upc": null | "012345678901",
  "status": "active" | "done" | "deleted",
  "disks": ["disk-1.json", "disk-2.json"],
  "created_at": "ISO8601",
  "completed_at": null | "ISO8601",
  "deleted_at": null | "ISO8601",
  "storage_path": "/path/to/collection/"
}
```

### disk-N.json
```json
{
  "disk_number": 1,
  "season": 1,
  "is_not_applicable": false,
  "drive_id": "drive-a",
  "status": "waiting" | "copying" | "done" | "failed",
  "copy_success": null | true | false,
  "bytes_copied": null | 1234567890,
  "output_dir": null | "/path/to/output/",
  "title": null | "Movie Title",
  "error": null | "Error message",
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "copy_started_at": null | "ISO8601",
  "copy_completed_at": null | "ISO8601"
}
```

## Ticket Map (frontier = open, unblocked, unassigned)

| # | Type | Title | Status |
|---|------|-------|--------|
| [#2](https://github.com/jstormes/media-backup/issues/2) | task | Setup MakeMKV on target system | **done** |
| [#3](https://github.com/jstormes/media-backup/issues/3) | research | MakeMKV interface test suite | **frontier** |
| [#4](https://github.com/jstormes/media-backup/issues/4) | prototype | F1/F2 keycode scanning test | **frontier** |
| [#5](https://github.com/jstormes/media-backup/issues/5) | prototype | Drive-closing copy trigger (udev) | **blocked by #2** |
| [#6](https://github.com/jstormes/media-backup/issues/6) | task | Write the Media Backup Build Spec | **blocked by #2, #3, #4, #5** |

## Frontier

Three parallel tickets are takeable: #2, #3, #4.

## Next step

Resolve the frontier tickets, then write the build spec (#6).
