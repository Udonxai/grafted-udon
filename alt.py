"""
AI-guided storage cleanup scanner for the Downloads folder.

Implements two classical AI-style approaches:
- Rule-based inference over file metadata and hashes.
- Greedy heuristic search scoring inspired by best-first search.

The tool never deletes files. It writes CSV reports for both approaches and
an additional comparison CSV to highlight agreement/disagreement.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import mimetypes
import os
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

DOWNLOADS_DEFAULT = os.path.expanduser("~/Downloads")
HASH_CHUNK_SIZE = 1024 * 1024  # 1 MiB

@dataclass
class FileRecord:
    path: str
    size: int
    age_days: float
    ext: str
    mime: Optional[str]
    sha256: str = ""
    reasons: List[str] = field(default_factory=list)

def iter_files(root: str) -> Iterable[str]:
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            yield os.path.join(dirpath, name)

def compute_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(HASH_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()

def load_files(root: str, max_files: Optional[int] = None) -> List[FileRecord]:
    records: List[FileRecord] = []
    now = time.time()
    for path in iter_files(root):
        try:
            st = os.stat(path)
        except OSError:
            continue
        age_days = (now - st.st_mtime) / 86400.0
        ext = os.path.splitext(path)[1].lower()
        mime, _ = mimetypes.guess_type(path)
        records.append(FileRecord(path=path, size=st.st_size, age_days=age_days, ext=ext, mime=mime))
        if max_files is not None and len(records) >= max_files:
            break
    return records

def index_hashes(records: List[FileRecord]) -> Dict[str, List[FileRecord]]:
    hash_map: Dict[str, List[FileRecord]] = {}
    for rec in records:
        try:
            rec.sha256 = compute_sha256(rec.path)
        except OSError:
            rec.reasons.append("hash_error")
            continue
        hash_map.setdefault(rec.sha256, []).append(rec)
    return hash_map

def rule_based_inference(rec: FileRecord, dup_map: Dict[str, List[FileRecord]], stale_threshold: int) -> Tuple[str, int, List[str]]:
    score = 0
    reasons: List[str] = []

    if rec.sha256 and len(dup_map.get(rec.sha256, [])) > 1:
        score += 5
        reasons.append("exact_dup")

    if rec.age_days > stale_threshold:
        score += 2
        reasons.append(f"old>{stale_threshold}d")

    if rec.age_days > 180:
        score += 1
        reasons.append("older>180d")

    risky_keep = {".exe", ".msi", ".bat", ".ps1", ".docx", ".xlsx", ".pptx", ".py"}
    if rec.ext in risky_keep:
        score -= 3
        reasons.append("risky_type")

    small_safe = rec.size < 32 * 1024
    if small_safe:
        score -= 1
        reasons.append("tiny_file")

    if score >= 5:
        rec_label = "delete_candidate"
    elif score >= 2:
        rec_label = "archive_candidate"
    else:
        rec_label = "keep"

    return rec_label, score, reasons

def heuristic_search(rec: FileRecord, dup_map: Dict[str, List[FileRecord]]) -> Tuple[str, int, List[str]]:
    score = 0
    reasons: List[str] = []
    # Heuristic features act as evaluation function for a best-first style rank.
    if rec.sha256 and len(dup_map.get(rec.sha256, [])) > 1:
        score += 6
        reasons.append("exact_dup")

    if rec.age_days > 365:
        score += 4
        reasons.append("very_old")
    elif rec.age_days > 180:
        score += 2
        reasons.append("old")
    elif rec.age_days > 90:
        score += 1
        reasons.append("stale90")

    if rec.size > 200 * 1024 * 1024:
        score += 2
        reasons.append("large")
    elif rec.size > 50 * 1024 * 1024:
        score += 1
        reasons.append("med_large")

    conservative_types = {".pdf", ".jpg", ".jpeg", ".png", ".zip", ".7z", ".mp4"}
    if rec.ext in conservative_types:
        score += 1
        reasons.append("common_dl")

    protect_types = {".exe", ".msi", ".bat", ".ps1", ".py", ".docx", ".xlsx", ".pptx"}
    if rec.ext in protect_types:
        score -= 4
        reasons.append("protect_type")
        
    if score >= 6:
        rec_label = "delete_candidate"
    elif score >= 3:
        rec_label = "archive_candidate"
    else:
        rec_label = "keep"

    return rec_label, score, reasons

def write_csv(path: str, rows: Iterable[List[object]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)

def run(root: str, output_dir: str, stale_threshold: int, max_files: Optional[int]) -> None:
    records = load_files(root, max_files=max_files)
    dup_map = index_hashes(records)

    rule_rows: List[List[object]] = [["path", "size_bytes", "age_days", "recommendation", "score", "reasons"]]
    search_rows: List[List[object]] = [["path", "size_bytes", "age_days", "recommendation", "score", "reasons"]]
    comparison_rows: List[List[object]] = [["path", "rule_rec", "search_rec", "note"]]

    for rec in records:
        rule_rec, rule_score, rule_reasons = rule_based_inference(rec, dup_map, stale_threshold)
        search_rec, search_score, search_reasons = heuristic_search(rec, dup_map)

        rule_rows.append([rec.path, rec.size, f"{rec.age_days:.1f}", rule_rec, rule_score, ";".join(rule_reasons)])
        search_rows.append([rec.path, rec.size, f"{rec.age_days:.1f}", search_rec, search_score, ";".join(search_reasons)])

        note = ""
        if rule_rec != search_rec:
            note = "disagree"
        elif rule_rec != "keep":
            note = "agree_action"
        comparison_rows.append([rec.path, rule_rec, search_rec, note])

    os.makedirs(output_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    rule_path = os.path.join(output_dir, f"cleanup_rule_based_{ts}.csv")
    search_path = os.path.join(output_dir, f"cleanup_search_{ts}.csv")
    compare_path = os.path.join(output_dir, f"cleanup_comparison_{ts}.csv")

    write_csv(rule_path, rule_rows)
    write_csv(search_path, search_rows)
    write_csv(compare_path, comparison_rows)

    print(f"Scanned {len(records)} files in {root}")
    print(f"Rule-based CSV: {rule_path}")
    print(f"Search CSV:     {search_path}")
    print(f"Comparison CSV: {compare_path}")
    print("No files were modified or deleted.")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI-guided Downloads cleanup scanner (report-only).")
    parser.add_argument("--root", default=DOWNLOADS_DEFAULT, help="Root folder to scan (default: ~/Downloads)")
    parser.add_argument("--output-dir", default="cleanup_reports", help="Directory for CSV outputs.")
    parser.add_argument("--stale-threshold", type=int, default=180, help="Days since modification to count as stale.")
    parser.add_argument("--max-files", type=int, default=None, help="Limit the scan to at most N files (for quick runs).")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    run(args.root, args.output_dir, args.stale_threshold, args.max_files)




