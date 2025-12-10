# grafted-udon
csci4511W final project

## How to Run

### Prerequisites
- Python 3.x
- Optional dependencies for image hashing: `Pillow`, `imagehash`
  ```bash
  pip install Pillow imagehash
  ```

### Main Scanner (`ai_cleanup.py`)
`ai_cleanup.py` is the recommended script for cleaning up your downloads. It uses a dual-engine approach (Rule-Based + Heuristic Search) to safely identify candidates for archiving or deletion. It generates comprehensive CSV reports and **never** modifies your files automatically.

**Basic Usage:**
Scans `~/Downloads` and saves reports to `cleanup_reports/`.
```bash
python ai_cleanup.py
```

**Custom Scan:**
```bash
python ai_cleanup.py --root "C:\path\to\target" --output-dir "my_reports"
```

**Options:**
- `--stale-threshold N`: Days to consider a file stale (default: 180).
- `--max-files N`: Limit the number of files scanned (useful for testing).

### Legacy Scanner (`scan.py`)
The original script `scan.py` is preserved for reference. It scans a directory and recommends files for cleanup based on simple age and duplication checks. 

**Basic Usage (Dry Run):**
This will generate a CSV report without moving any files.
```bash
python scan.py
```
By default, it scans `~/Downloads`.

**Specify a Directory:**
```bash
python scan.py --root "C:\path\to\folder"
```

**Execute Cleanup (Move Files):**
To actually move recommended files to a `cleanup_archive` folder:
```bash
python scan.py --no-dry-run
```

**Verbose Output:**
```bash
python scan.py --verbose
```


### Running the A* Prototype (`Folder Scan`)

The `Folder Scan` script demonstrates the A* decision algorithm.
```bash
python "Folder Scan"
```
