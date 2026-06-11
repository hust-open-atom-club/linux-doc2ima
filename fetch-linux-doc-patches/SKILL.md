---
name: fetch-linux-doc-patches
description: Fetch and archive Linux kernel documentation patches from the linux-doc mailing list via NNTP on lore.kernel.org. Use when Codex needs to set up, run, debug, or schedule a daily pull of LKML/linux-doc patch emails, save extracted .patch files, or maintain an incremental local patch inbox for later review.
---

# Fetch Linux Doc Patches

## Overview

Use this skill to pull patch submissions from the `linux-doc@vger.kernel.org` archive through lore.kernel.org NNTP, store them locally, and make the job repeatable as a daily task.

This follows the same ingestion-first shape as Sashiko: monitor kernel mailing list traffic, extract patch payloads, then hand the saved artifacts to downstream review or indexing tools.

## Quick Start

Run the bundled script from the skill directory:

```bash
python3 scripts/fetch_linux_doc_patches.py --output ./out/linux-doc-patches
```

For a daily pull, use the script's default stateful mode. It stores `.state.json` under the output directory and resumes from the last NNTP article number seen.

Use `--since-days 1` for a date-windowed one-day pull, or `--dry-run` to inspect matching messages without writing `.eml` and `.patch` files.

To fetch patches and add the newly saved patches to IMA, upload to the
`linux-doc邮件列表` knowledge base:

```bash
python3 scripts/fetch_linux_doc_patches.py --output ./out/linux-doc-patches --upload-to-ima
```

## Workflow

1. Confirm the target list and NNTP settings:
   - Server: `nntp.lore.kernel.org`
   - Port: `119`
   - Group: `org.kernel.vger.linux-doc`
2. Run `scripts/fetch_linux_doc_patches.py` with an output directory owned by the user or automation account.
3. Inspect `manifest.jsonl` for one JSON record per saved patch email.
4. Add `--upload-to-ima` when the saved patches should also be uploaded to the IMA `linux-doc邮件列表` knowledge base.
5. Schedule the same command daily with cron, systemd, or launchd. Read `references/scheduling.md` when setting up automation.
6. Feed saved `.patch` files or `.eml` files into downstream review tooling as needed.

## Script Behavior

The fetch script:

- Connects to lore NNTP on port 119 by default; use `--tls --port 563` only when TLS NNTP is reachable.
- Reads overview metadata before fetching full articles.
- Treats subjects containing `[PATCH` or `[RFC PATCH` as patch candidates.
- Skips `Re:` patch replies by default; use `--include-replies` when review threads are needed.
- Extracts the plain-text patch body or text/x-patch part as `.patch`.
- Writes append-only metadata to `manifest.jsonl`.
- Tracks the last processed article number in `.state.json` unless `--no-state` is used.
- When `--upload-to-ima` is set, converts each newly saved `.patch` file to an
  upload-only `.txt` copy because IMA file uploads do not accept `.patch`
  extensions. The original local `.patch` file is preserved.
- Looks up the IMA knowledge base named `linux-doc邮件列表` by default. Use
  `--ima-kb-id` or `--ima-kb-name` to override it.
- Keeps `.ima-upload-state.json` under the output directory so the same patch
  message is not uploaded twice.
- Groups IMA uploads by patch date when a matching date folder already exists
  in the knowledge base. If no date folder exists, the uploaded filename is
  prefixed with the date, for example `2026-06-11_1234-abcd.txt`.

The manifest keeps message IDs, authorship, threading-related headers available in overview metadata, and the local `.patch` path. Raw `.eml` files are not written by default.

## Common Commands

Fetch new messages since the last run:

```bash
python3 scripts/fetch_linux_doc_patches.py --output ~/lkml/linux-doc
```

Fetch new messages and upload them to IMA:

```bash
python3 scripts/fetch_linux_doc_patches.py --output ~/lkml/linux-doc --upload-to-ima
```

Fetch only the last day and ignore saved state:

```bash
python3 scripts/fetch_linux_doc_patches.py --output ~/lkml/linux-doc --since-days 1 --no-state
```

Preview up to 50 candidate articles:

```bash
python3 scripts/fetch_linux_doc_patches.py --output /tmp/linux-doc-preview --dry-run --max-articles 50
```

Use TLS if port 563 is available from the host:

```bash
python3 scripts/fetch_linux_doc_patches.py --output ~/lkml/linux-doc --tls --port 563
```

Upload to a specific IMA knowledge base ID:

```bash
python3 scripts/fetch_linux_doc_patches.py --output ~/lkml/linux-doc --upload-to-ima --ima-kb-id "<knowledge_base_id>"
```

## Troubleshooting

- If the group is unavailable, run with `--group org.kernel.vger.linux-doc` explicitly and verify lore NNTP is reachable from the host.
- If no patches are found, run with `--since-days 7 --dry-run` to distinguish an empty day from a stale state file.
- If article numbers have expired or reset, delete `.state.json` or use `--since-days`.
- If automation runs as another user, make sure that user can write the output directory and state file.
- If IMA upload fails with missing credentials, configure `IMA_OPENAPI_CLIENTID`
  and `IMA_OPENAPI_APIKEY`, or place credentials under `~/.config/ima/`.
- If date folders are required inside IMA, create the date folders in the
  `linux-doc邮件列表` knowledge base first; the script will use a matching
  existing folder automatically.
