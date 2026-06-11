# linux-doc2ima

Codex skill for fetching Linux kernel documentation patch emails from the
`linux-doc@vger.kernel.org` archive on lore.kernel.org and optionally uploading
newly saved patches to an IMA knowledge base.

## Skill

The skill lives in [`fetch-linux-doc-patches/`](fetch-linux-doc-patches/).

It includes:

- `SKILL.md`: Codex-facing instructions and trigger metadata.
- `scripts/fetch_linux_doc_patches.py`: NNTP fetcher and optional IMA uploader.
- `references/scheduling.md`: cron, systemd, and launchd examples.
- `agents/openai.yaml`: UI metadata for Codex skill listings.

## Install

Clone this repository and copy or symlink the skill directory into your Codex
skills directory:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -s "$(pwd)/fetch-linux-doc-patches" "${CODEX_HOME:-$HOME/.codex}/skills/fetch-linux-doc-patches"
```

Restart Codex after installing the skill so it can discover the metadata.

## Usage

Fetch new linux-doc patch emails and keep incremental state in the output
directory:

```bash
python3 fetch-linux-doc-patches/scripts/fetch_linux_doc_patches.py \
  --output ~/lkml/linux-doc
```

Preview recent matches without writing files:

```bash
python3 fetch-linux-doc-patches/scripts/fetch_linux_doc_patches.py \
  --output /tmp/linux-doc-preview \
  --since-days 1 \
  --no-state \
  --dry-run
```

Fetch new patches and upload them to the default IMA knowledge base named
`linux-doc邮件列表`:

```bash
python3 fetch-linux-doc-patches/scripts/fetch_linux_doc_patches.py \
  --output ~/lkml/linux-doc \
  --upload-to-ima
```

Use a specific IMA knowledge base ID:

```bash
python3 fetch-linux-doc-patches/scripts/fetch_linux_doc_patches.py \
  --output ~/lkml/linux-doc \
  --upload-to-ima \
  --ima-kb-id "<knowledge_base_id>"
```

## Requirements

- Python 3.10 or newer.
- Network access to `nntp.lore.kernel.org` on port `119`, or port `563` with
  `--tls --port 563` when TLS NNTP is reachable.
- Node.js and an installed `ima-skill` only when using `--upload-to-ima`.
- IMA credentials configured through `IMA_OPENAPI_CLIENTID` and
  `IMA_OPENAPI_APIKEY`, or through the credential file supported by
  `ima-skill`.

## Output

The fetcher writes:

- Daily directories containing extracted `.patch` files.
- `manifest.jsonl` with one record per saved patch email.
- `.state.json` for NNTP article resume state.
- `.ima-upload-state.json` when `--upload-to-ima` is enabled.

Generated output directories should not be committed to this repository.
