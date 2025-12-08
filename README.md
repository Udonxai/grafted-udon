# grafted-udon
csci4511W final project

## How to Run

### Prerequisites
- Python 3.x
- Optional dependencies for image hashing: `Pillow`, `imagehash`
  ```bash
  pip install Pillow imagehash
  ```

### Running the Scanner (`scan.py`)
The main script `scan.py` scans a directory and recommends files for cleanup (archive or delete) based on age, duplication, and similarity. It will not move or delete any files by default. 

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
