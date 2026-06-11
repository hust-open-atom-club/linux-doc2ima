#!/usr/bin/env python3
"""Fetch linux-doc patch emails from lore.kernel.org over NNTP."""

from __future__ import annotations

import argparse
import datetime as dt
import email
import email.policy
import hashlib
import json
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import warnings
from email.message import Message
from pathlib import Path
from typing import Any, Iterable

warnings.filterwarnings(
    "ignore",
    message="'nntplib' is deprecated.*",
    category=DeprecationWarning,
)

import nntplib


DEFAULT_SERVER = "nntp.lore.kernel.org"
DEFAULT_GROUP = "org.kernel.vger.linux-doc"
PATCH_SUBJECT_RE = re.compile(r"\[(?:RFC\s+)?PATCH[^\]]*\]", re.IGNORECASE)
DIFF_MARKERS = (
    "\ndiff --git ",
    "\n---\n",
    "\n--- a/",
    "\n+++ b/",
    "\n@@ ",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch linux-doc patch emails from lore.kernel.org via NNTP."
    )
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--group", default=DEFAULT_GROUP)
    parser.add_argument("--port", type=int, default=119)
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--no-state", action="store_true")
    parser.add_argument("--since-days", type=int)
    parser.add_argument("--max-articles", type=int)
    parser.add_argument("--overview-batch", type=int, default=200)
    parser.add_argument("--include-replies", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--upload-to-ima",
        action="store_true",
        help="Upload newly saved patches to the IMA knowledge base.",
    )
    parser.add_argument(
        "--ima-kb-name",
        default="linux-doc邮件列表",
        help="IMA knowledge base name to search when --ima-kb-id is not set.",
    )
    parser.add_argument("--ima-kb-id", help="IMA knowledge base ID.")
    parser.add_argument(
        "--ima-skill-dir",
        type=Path,
        default=Path.home() / ".codex/skills/ima-skill",
        help="Path to the installed ima-skill directory.",
    )
    parser.add_argument(
        "--ima-upload-state",
        type=Path,
        help="JSON state file tracking patches already uploaded to IMA.",
    )
    parser.add_argument(
        "--ima-duplicate",
        choices=("skip", "keep"),
        default="skip",
        help="How to handle a repeated filename in IMA.",
    )
    parser.add_argument(
        "--ima-upload-timeout",
        type=int,
        default=300000,
        help="COS upload timeout in milliseconds.",
    )
    return parser.parse_args()


def connect(args: argparse.Namespace) -> nntplib.NNTP:
    if not args.tls:
        return nntplib.NNTP(args.server, port=args.port, timeout=args.timeout)
    context = ssl.create_default_context()
    return nntplib.NNTP_SSL(
        args.server, port=args.port, timeout=args.timeout, ssl_context=context
    )


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(path)


def run_json_command(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(detail or f"Command failed: {' '.join(command)}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Command returned invalid JSON: {' '.join(command)}") from exc


def ima_api(ima_skill_dir: Path, api_path: str, body: dict[str, Any]) -> dict[str, Any]:
    script = ima_skill_dir / "ima_api.cjs"
    response = run_json_command(["node", str(script), api_path, json.dumps(body, ensure_ascii=False)])
    if response.get("code") != 0:
        raise RuntimeError(response.get("msg") or f"IMA API failed: {api_path}")
    data = response.get("data")
    return data if isinstance(data, dict) else {}


def find_ima_kb_id(args: argparse.Namespace) -> str:
    if args.ima_kb_id:
        return args.ima_kb_id
    data = ima_api(
        args.ima_skill_dir,
        "openapi/wiki/v1/search_knowledge_base",
        {"query": args.ima_kb_name, "cursor": "", "limit": 20},
    )
    matches = data.get("info_list") or []
    expected_name = args.ima_kb_name.replace(" ", "")
    exact = [
        item
        for item in matches
        if str(item.get("name") or item.get("kb_name") or "").replace(" ", "") == expected_name
    ]
    selected = exact[0] if exact else (matches[0] if matches else None)
    selected_id = (selected.get("id") or selected.get("kb_id")) if selected else None
    if not selected_id:
        raise RuntimeError(f"IMA knowledge base not found: {args.ima_kb_name}")
    return selected_id


def find_ima_date_folder(ima_skill_dir: Path, kb_id: str, day: str) -> str | None:
    data = ima_api(
        ima_skill_dir,
        "openapi/wiki/v1/search_knowledge",
        {"query": day, "cursor": "", "knowledge_base_id": kb_id},
    )
    for item in data.get("info_list") or []:
        if item.get("title") == day and str(item.get("media_id", "")).startswith("folder_"):
            return item["media_id"]
    return None


def patch_upload_name(record: dict[str, Any], folder_id: str | None) -> str:
    patch_path = Path(record["patch"])
    stem = patch_path.with_suffix("").name
    name = f"{stem}.txt"
    if folder_id:
        return name
    day = str(record.get("date") or patch_path.parent.name)[:10]
    return f"{day}_{name}"


def write_ima_upload_copy(record: dict[str, Any], target_dir: Path, file_name: str) -> Path:
    patch_path = Path(record["patch"])
    target_path = target_dir / file_name
    target_path.write_text(patch_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    return target_path


def preflight_upload_file(ima_skill_dir: Path, file_path: Path) -> dict[str, Any]:
    script = ima_skill_dir / "knowledge-base/scripts/preflight-check.cjs"
    return run_json_command(["node", str(script), "--file", str(file_path)])


def repeated_in_ima(
    ima_skill_dir: Path,
    kb_id: str,
    file_name: str,
    media_type: int,
    folder_id: str | None,
) -> bool:
    body: dict[str, Any] = {
        "params": [{"name": file_name, "media_type": media_type}],
        "knowledge_base_id": kb_id,
    }
    if folder_id:
        body["folder_id"] = folder_id
    data = ima_api(ima_skill_dir, "openapi/wiki/v1/check_repeated_names", body)
    results = data.get("results") or data.get("result") or []
    if isinstance(results, dict):
        results = list(results.values())
    return any(item.get("is_repeated") for item in results if isinstance(item, dict))


def timestamped_name(file_name: str) -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    path = Path(file_name)
    return f"{path.stem}_{stamp}{path.suffix}"


def upload_file_to_ima(
    args: argparse.Namespace,
    kb_id: str,
    file_path: Path,
    folder_id: str | None,
) -> str:
    meta = preflight_upload_file(args.ima_skill_dir, file_path)
    if not meta.get("pass"):
        raise RuntimeError(meta.get("reason") or f"IMA preflight failed: {file_path}")

    file_name = meta["file_name"]
    if repeated_in_ima(args.ima_skill_dir, kb_id, file_name, int(meta["media_type"]), folder_id):
        if args.ima_duplicate == "skip":
            return "skipped:duplicate"
        new_path = file_path.with_name(timestamped_name(file_name))
        shutil.copyfile(file_path, new_path)
        file_path = new_path
        meta = preflight_upload_file(args.ima_skill_dir, file_path)
        file_name = meta["file_name"]

    create_body = {
        "file_name": file_name,
        "file_size": int(meta["file_size"]),
        "content_type": meta["content_type"],
        "knowledge_base_id": kb_id,
        "file_ext": meta["file_ext"],
    }
    create_data = ima_api(args.ima_skill_dir, "openapi/wiki/v1/create_media", create_body)
    credential = create_data.get("cos_credential") or {}
    media_id = create_data.get("media_id")
    if not media_id or not credential:
        raise RuntimeError("IMA create_media response did not include media_id and cos_credential")

    upload_script = args.ima_skill_dir / "knowledge-base/scripts/cos-upload.cjs"
    upload_command = [
        "node",
        str(upload_script),
        "--file",
        str(file_path),
        "--secret-id",
        credential["secret_id"],
        "--secret-key",
        credential["secret_key"],
        "--token",
        credential["token"],
        "--bucket",
        credential["bucket_name"],
        "--region",
        credential["region"],
        "--cos-key",
        credential["cos_key"],
        "--content-type",
        meta["content_type"],
        "--start-time",
        str(credential["start_time"]),
        "--expired-time",
        str(credential["expired_time"]),
        "--timeout",
        str(args.ima_upload_timeout),
    ]
    upload_result = subprocess.run(upload_command, text=True, capture_output=True, check=False)
    if upload_result.returncode != 0:
        detail = upload_result.stderr.strip() or upload_result.stdout.strip()
        raise RuntimeError(detail or f"COS upload failed: {file_path}")

    add_body: dict[str, Any] = {
        "media_type": int(meta["media_type"]),
        "media_id": media_id,
        "title": file_name,
        "knowledge_base_id": kb_id,
        "file_info": {
            "cos_key": credential["cos_key"],
            "file_size": int(meta["file_size"]),
            "file_name": file_name,
        },
    }
    if folder_id:
        add_body["folder_id"] = folder_id
    ima_api(args.ima_skill_dir, "openapi/wiki/v1/add_knowledge", add_body)
    return media_id


def upload_records_to_ima(args: argparse.Namespace, records: list[dict[str, Any]], output: Path) -> None:
    patch_records = [record for record in records if record.get("patch")]
    if not patch_records:
        return

    upload_state_path = (
        args.ima_upload_state.expanduser()
        if args.ima_upload_state
        else output / ".ima-upload-state.json"
    )
    upload_state = load_state(upload_state_path)
    uploaded = set(upload_state.get("uploaded_message_ids", []))
    kb_id = find_ima_kb_id(args)
    uploaded_count = 0
    skipped_count = 0

    with tempfile.TemporaryDirectory(prefix="linux-doc-ima-") as tmp:
        tmp_dir = Path(tmp)
        folder_cache: dict[str, str | None] = {}
        for record in patch_records:
            upload_key = record.get("message_id") or str(record.get("article"))
            if upload_key in uploaded:
                skipped_count += 1
                continue

            day = str(record.get("date") or Path(record["patch"]).parent.name)[:10]
            if day not in folder_cache:
                folder_cache[day] = find_ima_date_folder(args.ima_skill_dir, kb_id, day)
            folder_id = folder_cache[day]
            upload_name = patch_upload_name(record, folder_id)
            upload_path = write_ima_upload_copy(record, tmp_dir, upload_name)
            result = upload_file_to_ima(args, kb_id, upload_path, folder_id)
            if result.startswith("skipped:"):
                skipped_count += 1
                continue
            uploaded.add(upload_key)
            uploaded_count += 1

    upload_state["uploaded_message_ids"] = sorted(uploaded)
    upload_state["knowledge_base_id"] = kb_id
    upload_state["knowledge_base_name"] = args.ima_kb_name
    upload_state["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    save_state(upload_state_path, upload_state)
    print(f"Uploaded {uploaded_count} patches to IMA; skipped {skipped_count}.")


def overview_date(value: str | bytes | None) -> dt.datetime | None:
    if not value:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    parsed = email.utils.parsedate_to_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def clean_header(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return " ".join(str(email.header.make_header(email.header.decode_header(value))).split())


def is_patch_subject(subject: str) -> bool:
    return bool(PATCH_SUBJECT_RE.search(subject))


def is_reply_subject(subject: str) -> bool:
    return subject.lower().startswith("re:")


def decode_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    charset = part.get_content_charset() or "utf-8"
    if payload is None:
        raw = part.get_payload()
        if isinstance(raw, str):
            return raw
        return ""
    return payload.decode(charset, errors="replace")


def iter_text_parts(msg: Message) -> Iterable[Message]:
    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            content_type = part.get_content_type()
            if content_type in {"text/plain", "text/x-patch", "text/x-diff"}:
                yield part
    elif msg.get_content_type() in {"text/plain", "text/x-patch", "text/x-diff"}:
        yield msg


def extract_patch_text(msg: Message) -> str:
    candidates = []
    for part in iter_text_parts(msg):
        text = decode_payload(part)
        score = sum(marker in f"\n{text}" for marker in DIFF_MARKERS)
        if part.get_content_type() in {"text/x-patch", "text/x-diff"}:
            score += 2
        candidates.append((score, text))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1].strip() + "\n"


def safe_stem(message_id: str, article_number: int) -> str:
    digest_source = message_id or str(article_number)
    digest = hashlib.sha256(digest_source.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{article_number}-{digest}"


def article_bytes(lines: list[bytes]) -> bytes:
    return b"\n".join(lines) + b"\n"


def overview_range(first: int, last: int) -> tuple[int, int]:
    if first > last:
        return last, last
    return first, last


def iter_overviews(
    client: nntplib.NNTP, start: int, end: int, batch_size: int
) -> Iterable[tuple[int, dict[str, Any]]]:
    current = start
    while current <= end:
        batch_end = min(end, current + batch_size - 1)
        _resp, overviews = client.over((current, batch_end))
        for article_number, overview in overviews:
            yield int(article_number), overview
        current = batch_end + 1


def main() -> int:
    args = parse_args()
    output = args.output.expanduser()
    state_path = args.state_file.expanduser() if args.state_file else output / ".state.json"
    group_key = f"{args.server}/{args.group}"
    state = {} if args.no_state else load_state(state_path)

    cutoff = None
    if args.since_days is not None:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.since_days)

    with connect(args) as client:
        _resp, _count, first_raw, last_raw, _name = client.group(args.group)
        first_available = int(first_raw)
        last_available = int(last_raw)
        state_last = int(state.get(group_key, {}).get("last_article", first_available - 1))
        start = max(first_available, state_last + 1)
        end = last_available
        start, end = overview_range(start, end)

        if args.max_articles and end - start + 1 > args.max_articles:
            start = end - args.max_articles + 1

        if start > end:
            print("No new NNTP articles to inspect.", file=sys.stderr)
            return 0

        saved = 0
        inspected = 0
        highest_seen = state_last
        manifest_records = []

        for number, overview in iter_overviews(client, start, end, args.overview_batch):
            highest_seen = max(highest_seen, number)
            inspected += 1
            subject = clean_header(overview.get("subject"))
            if not is_patch_subject(subject):
                continue
            if not args.include_replies and is_reply_subject(subject):
                continue
            sent_at = overview_date(overview.get("date"))
            if cutoff and sent_at and sent_at < cutoff:
                continue

            message_id = clean_header(overview.get("message-id"))
            author = clean_header(overview.get("from"))
            if args.dry_run:
                print(f"{number}\t{sent_at or ''}\t{author}\t{subject}")
                saved += 1
                continue

            _resp, info = client.article(str(number))
            raw = article_bytes(info.lines)
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            patch_text = extract_patch_text(msg)
            if not patch_text and not args.include_replies:
                continue

            day = (sent_at or dt.datetime.now(dt.timezone.utc)).date().isoformat()
            day_dir = output / day
            day_dir.mkdir(parents=True, exist_ok=True)
            stem = safe_stem(message_id, number)
            patch_path = None
            if patch_text:
                patch_path = day_dir / f"{stem}.patch"
                patch_path.write_text(patch_text, encoding="utf-8")

            record = {
                "article": number,
                "message_id": message_id,
                "date": sent_at.isoformat() if sent_at else None,
                "from": author,
                "subject": subject,
                "eml": None,
                "patch": str(patch_path) if patch_path else None,
            }
            manifest_records.append(record)
            saved += 1

    if not args.dry_run and manifest_records:
        output.mkdir(parents=True, exist_ok=True)
        with (output / "manifest.jsonl").open("a", encoding="utf-8") as handle:
            for record in manifest_records:
                handle.write(json.dumps(record, sort_keys=True) + "\n")

    if args.upload_to_ima and not args.dry_run:
        upload_records_to_ima(args, manifest_records, output)

    if not args.no_state and not args.dry_run:
        state[group_key] = {
            "last_article": highest_seen,
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        save_state(state_path, state)

    noun = "matching patch emails" if args.dry_run else "patch emails"
    print(f"Inspected {inspected} articles; saved {saved} {noun}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
