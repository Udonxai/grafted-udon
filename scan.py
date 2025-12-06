import os
import sys
import time
import math
import csv
import argparse
import hashlib
import multiprocessing as mp
from collections import defaultdict, Counter
from difflib import SequenceMatcher
from datetime import datetime

# Try optional image libs
try:
    from PIL import Image
    import imagehash
    IMAGEHASH_AVAILABLE = True
except Exception:
    IMAGEHASH_AVAILABLE = False

# --------------- CONFIG ---------------
SIZE_TOLERANCE = 1024           # bytes: group sizes within this tolerance for similarity checks
MAX_TEXT_PREVIEW = 20000        # bytes read for text similarity preview
MAX_TEXT_COMPARISONS = 8        # per file, compare to at most this many candidates
MIN_SIMILARITY_TEXT = 0.70      # threshold to consider text files similar
PHASH_DISTANCE_THRESHOLD = 8    # images
NUM_WORKERS = max(1, mp.cpu_count() - 1)
DRY_RUN_DEFAULT = True
REPORT_DIR = os.path.join(os.getcwd(), "cleanup_reports")
os.makedirs(REPORT_DIR, exist_ok=True)

# --------------- Progress bar ---------------
def progress_bar(prefix, current, total, bar_len=36):
    if total <= 0:
        return
    filled = int(bar_len * current / total)
    bar = "#" * filled + "-" * (bar_len - filled)
    pct = (current / total) * 100
    sys.stdout.write(f"\r{prefix}: [{bar}] {pct:5.1f}% ({current}/{total})")
    sys.stdout.flush()

# --------------- Helpers ---------------
def human_size(n):
    for unit in ['B','KB','MB','GB','TB']:
        if abs(n) < 1024.0:
            return f"{n:3.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"

def sha256_path(path):
    """Return SHA256 hex digest or None on error."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(65536), b""):
                h.update(block)
        return h.hexdigest()
    except Exception:
        return None

def read_text_preview(path, limit=MAX_TEXT_PREVIEW):
    try:
        with open(path, "r", errors="ignore") as f:
            return f.read(limit)
    except Exception:
        return None

def is_image_by_ext(path):
    ext = os.path.splitext(path)[1].lower()
    return ext in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}

def compute_phash(path):
    if not IMAGEHASH_AVAILABLE:
        return None
    try:
        img = Image.open(path)
        ph = imagehash.phash(img)
        return ph
    except Exception:
        return None

# --------------- Parallel helpers ---------------
def worker_sha256(paths):
    """Worker function for pool"""
    out = {}
    for p in paths:
        out[p] = sha256_path(p)
    return out

def parallel_sha256(all_paths):
    """Compute SHA256 for list of files using multiprocessing pool"""
    n = len(all_paths)
    if n == 0:
        return {}
    # split into chunks
    chunks = []
    chunk_size = max(1, n // (NUM_WORKERS * 4))
    for i in range(0, n, chunk_size):
        chunks.append(all_paths[i:i+chunk_size])

    results = {}
    with mp.Pool(processes=NUM_WORKERS) as pool:
        for i, res in enumerate(pool.imap(worker_sha256, chunks)):
            # merge
            results.update(res)
            progress_bar("Hashing files", min((i+1)*chunk_size, n), n)
    print()  # newline after progress bar
    return results

# --------------- Bucketing / candidate selection ---------------
def bucket_files(paths):
    """
    Return dict: (ext, size_bucket) , list(paths)
    """
    buckets = defaultdict(list)
    for p in paths:
        try:
            sz = os.path.getsize(p)
            ext = os.path.splitext(p)[1].lower()
            size_bucket = sz // max(1, SIZE_TOLERANCE)
            buckets[(ext, size_bucket)].append((p, sz))
        except Exception:
            continue
    return buckets

def expand_bucket_candidates(buckets):
    """
    For each bucket, produce a reduced list of candidate groups.
    Also create cross-buckets by nearby size buckets (±1) to catch files with small size changes.
    Returns list of candidate groups (each group is list of paths).
    """
    groups = []
    # iterate through keys and combine adjacent size buckets for same ext
    grouped_keys = defaultdict(list)
    for (ext, sb), items in buckets.items():
        grouped_keys[ext].append((sb, items))

    for ext, sb_items in grouped_keys.items():
        # sort by bucket
        sb_items.sort()
        # combine consecutive buckets where counts small
        for sb, items in sb_items:
            paths = [p for p, _ in items]
            groups.append(paths)
        # also add combined of adjacent buckets (sb and sb+1) to catch near-size duplicates
        for i in range(len(sb_items)-1):
            a = sb_items[i][1]
            b = sb_items[i+1][1]
            combined = [p for p,_ in a] + [p for p,_ in b]
            if len(combined) > 1:
                groups.append(combined)
    return groups

# --------------- Similarity checks within groups ---------------
def find_exact_duplicates_in_group(paths, sha_map):
    """Return list of lists where each list contains file paths that are byte-equal."""
    # group by sha
    groups = defaultdict(list)
    for p in paths:
        h = sha_map.get(p)
        if h is None:
            continue
        groups[h].append(p)
    # return only groups larger than 1
    return [g for g in groups.values() if len(g) > 1]

def find_text_similars(paths):
    """
    For text-like files in paths, compute text previews and compare smartly:
    - compute preview for each
    - for each file, score candidate similarities only against top-N by modified time closeness
    - returns list of (p1, p2, score)
    """
    previews = {}
    mtimes = {}
    for p in paths:
        t = read_text_preview(p)
        if t is None:
            continue
        previews[p] = t
        try:
            mtimes[p] = os.path.getmtime(p)
        except:
            mtimes[p] = 0

    results = []
    plist = list(previews.keys())
    n = len(plist)
    if n < 2:
        return results

    plist.sort(key=lambda x: mtimes.get(x, 0))

    for i, p in enumerate(plist):
        # choose neighbors around i (k on left and right)
        # This limits comparisons
        neighbors = []
        left = max(0, i - MAX_TEXT_COMPARISONS)
        right = min(n, i + MAX_TEXT_COMPARISONS + 1)
        for j in range(left, right):
            if j == i:
                continue
            neighbors.append(plist[j])

        # compute similarity only to these neighbors
        best_candidates = []
        t1 = previews[p]
        for q in neighbors:
            t2 = previews[q]
            try:
                sim = SequenceMatcher(None, t1, t2).ratio()
            except Exception:
                sim = 0.0
            if sim >= MIN_SIMILARITY_TEXT:
                results.append((p, q, sim))
    return results

def find_image_similars(paths):
    """If imagehash is available, compute pHash and compare within group."""
    if not IMAGEHASH_AVAILABLE:
        return []
    phashes = {}
    for p in paths:
        if not is_image_by_ext(p):
            continue
        ph = compute_phash(p)
        if ph is not None:
            phashes[p] = ph
    results = []
    keys = list(phashes.keys())
    m = len(keys)
    for i in range(m):
        for j in range(i+1, m):
            a, b = keys[i], keys[j]
            try:
                d = phashes[a] - phashes[b]
            except Exception:
                continue
            if d <= PHASH_DISTANCE_THRESHOLD:
                results.append((a, b, d))
    return results

# --------------- Scoring and decision engine (AI-ish) ---------------
def score_and_recommend(file_metadata, duplicate_groups_map, similar_pairs_map):
    """
    file_metadata: dict path , {size, age_days, ext}
    duplicate_groups_map: path , canonical path (for duplicates)
    similar_pairs_map: dict of pair,score
    Returns recommendation: 'keep', 'archive_candidate', 'delete_candidate' and a numeric score
    """
    p = file_metadata["path"]
    age = file_metadata["age_days"]
    ext = file_metadata["ext"]
    size = file_metadata["size"]

    score = 0
    reasons = []

    # Age heuristic
    if age > 365:
        score += 3
        reasons.append("old>365d")
    elif age > 180:
        score += 2
        reasons.append("old>180d")
    elif age > 90:
        score += 1
        reasons.append("old>90d")

    # Exact duplicate
    if p in duplicate_groups_map:
        score += 5
        reasons.append("exact_dup")

    # Similar pairs
    sim_score = 0
    # check any pair involving p
    for (a,b), s in similar_pairs_map.items():
        if a == p or b == p:
            sim_score = max(sim_score, s)
    if sim_score >= 0.95:
        score += 4; reasons.append("very_similar")
    elif sim_score >= 0.8:
        score += 2; reasons.append(f"similar={sim_score:.2f}")

    # ext-based risk
    risky_keep_ext = {".py", ".exe", ".msi", ".docx", ".xlsx", ".pptx"}
    if ext in risky_keep_ext:
        score -= 5
        reasons.append("risky_ext")

    # Decide based on score
    if score >= 6:
        rec = "delete_candidate"
    elif score >= 3:
        rec = "archive_candidate"
    else:
        rec = "keep"
    return rec, score, reasons

# --------------- Main pipeline ---------------
def run_pipeline(root, dry_run=True, verbose=False):
    root = os.path.abspath(root)
    print(f"Scanning root: {root}")

    # Collect all files
    all_files = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            all_files.append(path)
    total_files = len(all_files)
    print(f"Found {total_files} files.")

    if total_files == 0:
        return

    # Bucket by extension & size
    print("Bucketing files (fast)...")
    buckets = bucket_files(all_files)

    # Expand candidate groups to test
    candidate_groups = expand_bucket_candidates(buckets)
    candidate_groups = [g for g in candidate_groups if len(g) > 1]
    print(f"Candidate groups for deeper checks: {len(candidate_groups)}")

    # Compute SHA256 for files that appear in any candidate group (only those)
    # Build set of files_to_hash
    files_to_hash = set()
    for g in candidate_groups:
        for p in g:
            files_to_hash.add(p)
    files_to_hash = list(files_to_hash)
    print(f"Computing SHA256 for {len(files_to_hash)} candidate files (parallel)...")
    sha_map = parallel_sha256(files_to_hash)

    # Find exact duplicates inside each candidate group using SHA
    exact_duplicates_groups = []
    for g in candidate_groups:
        ed = find_exact_duplicates_in_group(g, sha_map)
        exact_duplicates_groups.extend(ed)

    # Build map path
    duplicate_groups_map = {}
    for grp in exact_duplicates_groups:
        canon = grp[0]
        for member in grp:
            duplicate_groups_map[member] = canon

    # Within each group compute text and image similars
    print("Computing content-similarity (bounded per group)...")
    similar_pairs = []  # list of tuples (a,b,score) where score numeric
    group_count = len(candidate_groups)
    for i, g in enumerate(candidate_groups):
        progress_bar("Groups processed", i+1, group_count)
        # split group into text-like and image-like and others
        text_files = [p for p in g if not is_image_by_ext(p)]
        image_files = [p for p in g if is_image_by_ext(p)]
        # text similarity
        tsim = find_text_similars(text_files)
        similar_pairs.extend(tsim)
        # image similarity
        if IMAGEHASH_AVAILABLE:
            isim = find_image_similars(image_files)
            # convert phash distance to a normalized similarity score
            isim_norm = [(a,b, max(0.0, 1.0 - d/PHASH_DISTANCE_THRESHOLD)) for (a,b,d) in isim]
            similar_pairs.extend(isim_norm)
    print()

    # Build a map of pair , score (max score if multiple reported)
    similar_pairs_map = {}
    for a,b,s in similar_pairs:
        key = (a,b) if a < b else (b,a)
        similar_pairs_map[key] = max(similar_pairs_map.get(key, 0.0), s)

    # Compute metadata for scoring
    file_meta = {}
    for p in all_files:
        try:
            st = os.stat(p)
            file_meta[p] = {
                "path": p,
                "size": st.st_size,
                "age_days": (time.time() - st.st_mtime)/86400.0,
                "ext": os.path.splitext(p)[1].lower()
            }
        except Exception:
            continue

    # Score & recommend
    print("Scoring and producing recommendations...")
    recommendations = {}
    for p, meta in file_meta.items():
        rec, score, reasons = score_and_recommend(
            {"path": p, "size": meta["size"], "age_days": meta["age_days"], "ext": meta["ext"]},
            duplicate_groups_map, similar_pairs_map
        )
        recommendations[p] = {"recommendation": rec, "score": score, "reasons": reasons}

    # Produce CSV report
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(REPORT_DIR, f"cleanup_report_{ts}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as cf:
        writer = csv.writer(cf)
        writer.writerow(["path","size","age_days","recommendation","score","reasons"])
        for p, meta in file_meta.items():
            rec = recommendations[p]["recommendation"]
            score = recommendations[p]["score"]
            reasons = ";".join(recommendations[p]["reasons"])
            writer.writerow([p, meta["size"], f"{meta['age_days']:.1f}", rec, score, reasons])
    print(f"Report written to: {csv_path}")

    # Summary counts
    cnt = Counter([r["recommendation"] for r in recommendations.values()])
    print("Summary:", dict(cnt))

    # If not dry-run, perform safe archive moves for archive_candidate and delete_candidate , move to archive folder
    if not dry_run:
        archive_root = os.path.join(root, "cleanup_archive")
        os.makedirs(archive_root, exist_ok=True)
        print(f"Moving candidates to archive folder: {archive_root}")
        for p, info in recommendations.items():
            rec = info["recommendation"]
            if rec in ("archive_candidate", "delete_candidate"):
                try:
                    dest = os.path.join(archive_root, os.path.basename(p))
                    # avoid overwriting same-named files
                    if os.path.exists(dest):
                        base, ext = os.path.splitext(dest)
                        dest = f"{base}_{int(time.time())}{ext}"
                    os.rename(p, dest)
                except Exception as e:
                    print("Error moving", p, e)

    return csv_path, recommendations

# --------------- CLI ---------------
# Command-line argument handling for the cleanup script
def parse_cli():
    ap = argparse.ArgumentParser(description="AI-styled fast cleanup (offline, scalable)")
    ap.add_argument("--root", "-r", type=str, default=os.path.expanduser("~/Downloads"), help="Root folder to scan")
    ap.add_argument("--no-dry-run", action="store_true", help="Actually move candidate files to cleanup_archive (default is dry-run)")
    ap.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    return ap.parse_args()

if __name__ == "__main__":
    args = parse_cli()
    csv_path, recs = run_pipeline(args.root, dry_run=(not args.no_dry_run), verbose=args.verbose)
    print("Done.")
