from __future__ import annotations

from pathlib import Path
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from app.invoice_ocr import invoice_ocr

    samples_dir = root / "samples"
    if not samples_dir.exists():
        print(f"[ERROR] Missing samples directory: {samples_dir}")
        return 1

    candidates = sorted(
        [
            path
            for path in samples_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf"}
        ]
    )[:5]
    if not candidates:
        print(f"[ERROR] No sample files found in {samples_dir}")
        return 1

    print(f"Running invoice-table OCR on {len(candidates)} sample(s)")
    for path in candidates:
        print("\n" + "=" * 80)
        print(f"File: {path.name}")
        result = invoice_ocr(str(path), save_debug=False)
        metrics = result.get("quality_metrics", {})
        rows = result.get("table_rows_structured", [])
        print(f"mean_conf: {metrics.get('mean_conf')}")
        print(f"rows_detected: {len(rows)}")
        print("rows_preview:")
        for row in rows[:3]:
            print(
                f"  - desc={row.get('description', '')!r}, "
                f"qty={row.get('quantity', '')!r}, "
                f"unit={row.get('unit_price', '')!r}, "
                f"total={row.get('line_total', '')!r}"
            )
        if not rows:
            print("  (no structured rows)")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
