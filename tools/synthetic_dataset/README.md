# Synthetic Invoice Dataset Generator

Isolated tool to generate synthetic invoice datasets (PDF + PNG + JSON ground truth) for OCR testing.

This module is fully independent and does not import or modify any project backend/frontend code.

## Folder structure

```
tools/synthetic_dataset/
  generate.py
  requirements.txt
  templates/
    template_01.html
    template_02.html
    template_03.html
  output/
    pdfs/
    images/
    labels/
```

## Features

- Random FR data (`faker fr_FR`)
- Invoice fields:
  - `invoice_number` (`INV-YYYY-XXXXXX`)
  - `date` (within last 120 days)
  - `supplier` (name, address, phone, ICE 15 digits)
  - `client` (name, address, ICE)
  - `items` (3 to 12 lines)
  - `subtotal`, `tva_rate`, `tva_amount`, `total_ttc`, `currency` (`MAD`)
- 3 HTML templates with different layouts
- Rendering options: PDF / PNG / both
- Optional image noise: none / low / medium

## Installation

### Windows (PowerShell)

```powershell
cd tools/synthetic_dataset
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

### Linux/macOS

```bash
cd tools/synthetic_dataset
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Usage

From project root:

```bash
python tools/synthetic_dataset/generate.py --count 1000 --out tools/synthetic_dataset/output --seed 42 --render both --noise low --templates all
```

Minimal example:

```bash
python tools/synthetic_dataset/generate.py --count 5
```

Default behavior:
- `--count` defaults to `10`
- output defaults to `tools/synthetic_dataset/output`
- `--render` defaults to `both`
- `--noise` defaults to `none`
- `--templates` defaults to `all`

## CLI options

- `--count` (int)
- `--out` (path)
- `--seed` (int)
- `--render` (`pdf|png|both`)
- `--noise` (`none|low|medium`)
- `--templates` (`all|1|2|3`)

## Output naming

For each invoice:
- `pdfs/INV-YYYY-XXXXXX.pdf` (if `render=pdf|both`)
- `images/INV-YYYY-XXXXXX.png` (if `render=png|both`)
- `labels/INV-YYYY-XXXXXX.json` (always)

## Notes

- PNG files are generated from the first page of the rendered PDF.
- If `--render png` is used, the generator creates a temporary PDF internally for conversion, then removes it.
