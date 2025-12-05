import os
import time
import hashlib
import heapq
from difflib import SequenceMatcher
import sys


# Progress Bar Utilities


def progress_bar(current, total, bar_length=40):
    filled = int(bar_length * current / total)
    bar = "#" * filled + "-" * (bar_length - filled)
    percent = (current / total) * 100
    sys.stdout.write(f"\rScanning files: [{bar}] {percent:5.1f}%")
    sys.stdout.flush()


# Utilities


def sha256_file(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                h.update(chunk)
        return h.hexdigest()
    except:
        return None

def text_preview(path, limit=5000):
    try:
        with open(path, "r", errors="ignore") as f:
            return f.read(limit)
    except:
        return ""

def file_age_days(path):
    now = time.time()
    last_access = os.path.getatime(path)
    return (now - last_access) / 86400


# A* Heuristic


def heuristic(file_info):
    score = 0

    # Age heuristic
    age = file_info["age"]
    if age > 180:
        score += 5
    elif age > 90:
        score += 3
    elif age > 30:
        score += 1

    # Duplicate heuristic
    if file_info["is_exact_duplicate"]:
        score += 6

    if file_info["similarity"] > 0.90:
        score += 4
    elif file_info["similarity"] > 0.75:
        score += 2

    # Risky file types
    risky_ext = [".docx", ".xlsx", ".py", ".c", ".cpp"]
    if file_info["extension"] in risky_ext:
        score -= 5

    return -score


# A* Decision


ACTIONS = ["keep", "archive", "delete"]

def a_star_decide(file_info):
    pq = []
    visited = set()
    start = ("keep", 0)
    heapq.heappush(pq, (heuristic(file_info), start))

    while pq:
        cost, (action, depth) = heapq.heappop(pq)

        if action not in visited:
            visited.add(action)

            if depth == 1:
                return action

            for next_action in ACTIONS:
                next_state = (next_action, depth + 1)
                heapq.heappush(pq, (heuristic(file_info), next_state))

    return "keep"


# Main Folder Scan


def scan_folder(root):
    print(f"Scanning: {root}\n")

    all_files = []

    # First pass: count files for progress bar
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            all_files.append(os.path.join(dirpath, name))

    total_files = len(all_files)
    if total_files == 0:
        print("No files found.")
        return []

    hash_map = {}
    previews = {}
    files = []

    # Second pass: gather metadata with progress bar
    for i, path in enumerate(all_files):
        progress_bar(i + 1, total_files)

        ext = os.path.splitext(path)[1].lower()
        age = file_age_days(path)
        h = sha256_file(path)
        preview = text_preview(path)

        previews[path] = preview

        if h not in hash_map:
            hash_map[h] = []
        hash_map[h].append(path)

        files.append({
            "path": path,
            "hash": h,
            "extension": ext,
            "age": age,
            "preview": preview
        })

    print("\nCalculating duplicate & similarity scores...")

    # Compute duplicates & similarity
    for f in files:
        h = f["hash"]
        f["is_exact_duplicate"] = len(hash_map[h]) > 1

        max_sim = 0
        for other in files:
            if other["path"] == f["path"]:
                continue
            sim = SequenceMatcher(None, f["preview"], other["preview"]).ratio()
            if sim > max_sim:
                max_sim = sim

        f["similarity"] = max_sim

    print("Running AI A* decision engine...\n")

    results = []
    for f in files:
        action = a_star_decide(f)
        results.append((f["path"], action, f["age"], f["is_exact_duplicate"], f["similarity"]))

    return results



# Run


if __name__ == "__main__":
    folder = os.path.expanduser("~/Downloads")
    results = scan_folder(folder)

    print("\n--- RESULTS ---")
    for path, action, age, dup, sim in results:
        print(f"\nFile: {path}")
        print(f"  Suggested: {action.upper()}")
        print(f"  Age: {age:.1f} days")
        print(f"  Exact Duplicate: {dup}")
        print(f"  Similarity Score: {sim:.2f}")
