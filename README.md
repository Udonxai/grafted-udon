# grafted-udon
csci4511W final project

## How to Run

### Prerequisites
- Python 3.x


### Main Scanner (`ai_cleanup.py`)
`ai_cleanup.py` is the script for cleaning up your downloads. It uses a dual-engine approach (Rule-Based + Heuristic Search) to safely identify candidates for archiving or deletion. It generates comprehensive CSV reports and **never** modifies your files automatically.

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
