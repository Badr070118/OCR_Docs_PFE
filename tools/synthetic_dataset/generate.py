import argparse
import json
import logging
import random
import sys
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz
from faker import Faker
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image, ImageEnhance, ImageFilter
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

TVA_RATES = [7, 10, 14, 20]
NOISE_PRESETS = {
    "none": {"rotation": 0.0, "blur": 0.0, "contrast": 1.0, "sigma": 0.0, "alpha": 0.0},
    "low": {"rotation": 0.7, "blur": 0.35, "contrast": 1.03, "sigma": 8.0, "alpha": 0.05},
    "medium": {"rotation": 1.5, "blur": 0.8, "contrast": 1.06, "sigma": 14.0, "alpha": 0.08},
}


def parse_args() -> argparse.Namespace:
    default_output = Path(__file__).resolve().parent / "output"
    parser = argparse.ArgumentParser(
        description="Generate synthetic invoices dataset (PDF + PNG + JSON labels)."
    )
    parser.add_argument("--count", type=int, default=10, help="Number of invoices to generate (default: 10)")
    parser.add_argument("--out", type=Path, default=default_output, help="Output root directory")
    parser.add_argument("--seed", type=int, default=None, help="Optional random seed")
    parser.add_argument("--render", choices=["pdf", "png", "both"], default="both", help="Output format")
    parser.add_argument(
        "--noise",
        choices=["none", "low", "medium"],
        default="none",
        help="Apply optional scan-like noise to PNG",
    )
    parser.add_argument(
        "--templates",
        choices=["all", "1", "2", "3"],
        default="all",
        help="Template selection",
    )
    return parser.parse_args()


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money_to_text(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", " ")


def random_ice(rng: random.Random) -> str:
    return "".join(rng.choice("0123456789") for _ in range(15))


def random_invoice_date(rng: random.Random) -> date:
    days_back = rng.randint(0, 120)
    return date.today() - timedelta(days=days_back)


def build_party(fake: Faker, rng: random.Random, include_phone: bool) -> Dict[str, Any]:
    party: Dict[str, Any] = {
        "name": fake.company(),
        "address": f"{fake.street_address()}, {fake.postcode()} {fake.city()}",
        "ice": random_ice(rng),
    }
    if include_phone:
        party["phone"] = fake.phone_number()
    return party


def build_items(fake: Faker, rng: random.Random) -> List[Dict[str, Any]]:
    lines: List[Dict[str, Any]] = []
    line_count = rng.randint(3, 12)
    for _ in range(line_count):
        qty = rng.randint(1, 20)
        unit_price = round_money(Decimal(str(rng.uniform(25, 4500))))
        total = round_money(unit_price * Decimal(qty))
        description = f"{fake.bs().capitalize()} - {fake.word().capitalize()}"
        lines.append(
            {
                "description": description,
                "qty": qty,
                "unit_price": unit_price,
                "total": total,
            }
        )
    return lines


def pick_template_ids(template_arg: str) -> List[int]:
    if template_arg == "all":
        return [1, 2, 3]
    return [int(template_arg)]


def build_invoice_payload(index: int, fake: Faker, rng: random.Random, template_id: int) -> Dict[str, Any]:
    invoice_date = random_invoice_date(rng)
    invoice_number = f"INV-{invoice_date.year}-{index:06d}"

    supplier = build_party(fake, rng, include_phone=True)
    client = build_party(fake, rng, include_phone=False)
    items = build_items(fake, rng)

    subtotal = round_money(sum((item["total"] for item in items), Decimal("0.00")))
    tva_rate = rng.choice(TVA_RATES)
    tva_amount = round_money(subtotal * Decimal(tva_rate) / Decimal(100))
    total_ttc = round_money(subtotal + tva_amount)

    payload = {
        "invoice_number": invoice_number,
        "date": invoice_date.strftime("%d/%m/%Y"),
        "supplier": supplier,
        "client": client,
        "items": [
            {
                "description": item["description"],
                "qty": item["qty"],
                "unit_price": float(item["unit_price"]),
                "total": float(item["total"]),
            }
            for item in items
        ],
        "subtotal": float(subtotal),
        "tva_rate": tva_rate,
        "tva_amount": float(tva_amount),
        "total_ttc": float(total_ttc),
        "currency": "MAD",
        "template_id": template_id,
    }

    render_context = {
        "invoice_number": payload["invoice_number"],
        "invoice_date": payload["date"],
        "supplier": supplier,
        "client": client,
        "items": [
            {
                "description": item["description"],
                "qty": item["qty"],
                "unit_price": money_to_text(item["unit_price"]),
                "total": money_to_text(item["total"]),
            }
            for item in items
        ],
        "subtotal": money_to_text(subtotal),
        "tva_rate": tva_rate,
        "tva_amount": money_to_text(tva_amount),
        "total_ttc": money_to_text(total_ttc),
        "currency": "MAD",
        "note": fake.sentence(nb_words=10),
    }
    return {"label": payload, "render": render_context}


def write_json(label_path: Path, payload: Dict[str, Any]) -> None:
    label_path.parent.mkdir(parents=True, exist_ok=True)
    with label_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def html_to_pdf(page: Any, html: str, pdf_path: Path) -> None:
    page.set_content(html, wait_until="networkidle")
    page.pdf(
        path=str(pdf_path),
        format="A4",
        print_background=True,
        margin={"top": "10mm", "right": "10mm", "bottom": "10mm", "left": "10mm"},
    )


def apply_noise_to_png(image_path: Path, noise_level: str, rng: random.Random) -> None:
    preset = NOISE_PRESETS[noise_level]
    if noise_level == "none":
        return

    with Image.open(image_path).convert("RGB") as img:
        rotation_limit = float(preset["rotation"])
        if rotation_limit > 0:
            img = img.rotate(rng.uniform(-rotation_limit, rotation_limit), expand=True, fillcolor=(255, 255, 255))

        blur_radius = float(preset["blur"])
        if blur_radius > 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))

        contrast = float(preset["contrast"])
        if contrast != 1.0:
            img = ImageEnhance.Contrast(img).enhance(contrast)

        sigma = float(preset["sigma"])
        alpha = float(preset["alpha"])
        if sigma > 0 and alpha > 0:
            noise = Image.effect_noise(img.size, sigma).convert("L")
            noise_rgb = Image.merge("RGB", (noise, noise, noise))
            img = Image.blend(img, noise_rgb, alpha)

        img.save(image_path, format="PNG", optimize=True)


def pdf_to_png(pdf_path: Path, png_path: Path, noise_level: str, rng: random.Random) -> None:
    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(0)
        matrix = fitz.Matrix(2.0, 2.0)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        pixmap.save(str(png_path))
    finally:
        doc.close()

    apply_noise_to_png(png_path, noise_level, rng)


def ensure_output_dirs(root: Path) -> Dict[str, Path]:
    dirs = {
        "root": root,
        "pdfs": root / "pdfs",
        "images": root / "images",
        "labels": root / "labels",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def run_generation(args: argparse.Namespace) -> int:
    if args.count <= 0:
        logging.error("--count must be > 0")
        return 2

    seed_value = args.seed if args.seed is not None else random.randrange(1, 10_000_000)
    rng = random.Random(seed_value)
    fake = Faker("fr_FR")
    fake.seed_instance(seed_value)

    template_ids = pick_template_ids(args.templates)
    script_dir = Path(__file__).resolve().parent
    template_dir = script_dir / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(enabled_extensions=("html",)),
    )

    output_dirs = ensure_output_dirs(Path(args.out))

    need_pdf = args.render in {"pdf", "both"}
    need_png = args.render in {"png", "both"}

    logging.info("Seed: %s", seed_value)
    logging.info("Generating %s invoices using templates %s", args.count, template_ids)
    logging.info("Output root: %s", output_dirs["root"])

    generated = 0
    failed = 0

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(locale="fr-FR")
            page = context.new_page()

            for i in range(1, args.count + 1):
                template_id = rng.choice(template_ids)
                template_name = f"template_0{template_id}.html"

                try:
                    payload = build_invoice_payload(i, fake, rng, template_id)
                    stem = payload["label"]["invoice_number"]

                    label_path = output_dirs["labels"] / f"{stem}.json"
                    pdf_path = output_dirs["pdfs"] / f"{stem}.pdf"
                    png_path = output_dirs["images"] / f"{stem}.png"
                    temp_pdf_path: Optional[Path] = None

                    html = env.get_template(template_name).render(**payload["render"])

                    if need_pdf:
                        html_to_pdf(page, html, pdf_path)
                    elif need_png:
                        temp_pdf_path = output_dirs["pdfs"] / f"{stem}.__tmp__.pdf"
                        html_to_pdf(page, html, temp_pdf_path)

                    if need_png:
                        source_pdf = pdf_path if need_pdf else temp_pdf_path
                        if source_pdf is None:
                            raise RuntimeError("Internal error: missing source PDF for PNG conversion")
                        pdf_to_png(source_pdf, png_path, args.noise, rng)

                    write_json(label_path, payload["label"])

                    if temp_pdf_path and temp_pdf_path.exists():
                        temp_pdf_path.unlink(missing_ok=True)

                    generated += 1
                    if generated % 25 == 0 or generated == args.count:
                        logging.info("Progress: %s/%s generated", generated, args.count)

                except Exception as invoice_exc:
                    failed += 1
                    logging.exception("Invoice %s failed: %s", i, invoice_exc)

            context.close()
            browser.close()

    except PlaywrightError as e:
        logging.error("Playwright failed: %s", e)
        logging.error("Install browser binaries with: python -m playwright install chromium")
        return 1
    except Exception as e:
        logging.error("Fatal generation error: %s", e)
        return 1

    logging.info("Done. Success=%s Failed=%s", generated, failed)
    return 0 if generated > 0 else 1


def main() -> int:
    setup_logging()
    args = parse_args()
    return run_generation(args)


if __name__ == "__main__":
    sys.exit(main())
