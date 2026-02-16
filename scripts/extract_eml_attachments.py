#!/usr/bin/env python3
"""Extract PDF attachments from .eml files for eval fixtures.

One-time script to populate backend/tests/eval/fixtures/attachments/
with real PDF files referenced by eval fixture JSON.

Usage:
    uv run python scripts/extract_eml_attachments.py
"""

import email
import sys
from pathlib import Path

# Source .eml files → (attachment content-type prefix, attachment filename substring) → target filename
EXTRACTIONS = [
    {
        "eml": "20250315_072524124_iOS.heic.eml",
        "match_filename": "January",
        "target": "january_2026_kindercare.pdf",
    },
    {
        "eml": "December Calender 2025 [C109419390].eml",
        "match_filename": "december",
        "target": "december_2025_kindercare.pdf",
    },
    {
        "eml": "December Calender 2025 [C109419390].eml",
        "match_filename": "Red",
        "target": "holiday_lunch_invitation.pdf",
        "crop_first_page": True,
    },
    {
        "eml": "In class performances Thursday Dec 11.eml",
        "match_filename": "Holiday",
        "target": "winter_dance_performance.pdf",
    },
    {
        "eml": "Statement from WALNUT HEIGHTS",
        "match_filename": "Statement",
        "target": "walnut_heights_statement.pdf",
    },
]

EML_DIR = Path.home() / "Downloads" / "new_evals"
TARGET_DIR = Path(__file__).parent.parent / "backend" / "tests" / "eval" / "fixtures" / "attachments"


def find_eml(pattern: str) -> Path:
    """Find an .eml file matching the pattern prefix."""
    for f in EML_DIR.iterdir():
        if f.name.startswith(pattern) and f.suffix == ".eml":
            return f
    raise FileNotFoundError(f"No .eml file matching '{pattern}' in {EML_DIR}")


def extract_pdf(eml_path: Path, match_filename: str) -> bytes:
    """Extract a PDF attachment whose filename contains match_filename."""
    with open(eml_path, "rb") as f:
        msg = email.message_from_binary_file(f)

    for part in msg.walk():
        content_type = part.get_content_type()
        if content_type != "application/pdf":
            continue
        filename = part.get_filename() or ""
        if match_filename.lower() in filename.lower():
            payload = part.get_payload(decode=True)
            if payload:
                return payload

    raise ValueError(
        f"No PDF attachment matching '{match_filename}' in {eml_path.name}"
    )


def crop_to_first_page(pdf_data: bytes) -> bytes:
    """Crop a PDF to its first page only (reduces large PDFs)."""
    import fitz

    doc = fitz.open(stream=pdf_data, filetype="pdf")
    if len(doc) <= 1:
        result = pdf_data
    else:
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=0, to_page=0)
        result = new_doc.tobytes()
        new_doc.close()
    doc.close()
    return result


def main():
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    success = 0
    for spec in EXTRACTIONS:
        try:
            eml_path = find_eml(spec["eml"])
            pdf_data = extract_pdf(eml_path, spec["match_filename"])

            if spec.get("crop_first_page"):
                original_size = len(pdf_data)
                pdf_data = crop_to_first_page(pdf_data)
                print(
                    f"  Cropped {spec['target']}: "
                    f"{original_size:,} -> {len(pdf_data):,} bytes"
                )

            target_path = TARGET_DIR / spec["target"]
            target_path.write_bytes(pdf_data)
            print(f"  Extracted: {spec['target']} ({len(pdf_data):,} bytes)")
            success += 1
        except Exception as e:
            print(f"  FAILED: {spec['target']}: {e}", file=sys.stderr)

    print(f"\n{success}/{len(EXTRACTIONS)} PDFs extracted to {TARGET_DIR}")
    return 0 if success == len(EXTRACTIONS) else 1


if __name__ == "__main__":
    sys.exit(main())
