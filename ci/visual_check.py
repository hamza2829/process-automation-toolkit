"""Render the actual workbook through LibreOffice, then inspect every PDF page."""
import json
from pathlib import Path

import pymupdf
from openpyxl import load_workbook
from PIL import Image, ImageDraw

root = Path("artifacts")
previews = root / "previews"
previews.mkdir(exist_ok=True)
document = pymupdf.open(previews / "weekly-report.pdf")
book = load_workbook(root / "weekly-report.xlsx")
all_text = "\n".join(page.get_text() for page in document)
for sheet in book:
    assert sheet["A2"].value in all_text, sheet.title
assert "Requests per department" in all_text
assert "#REF!" not in all_text and "#VALUE!" not in all_text
tiles = []
for index, page in enumerate(document):
    path = previews / f"weekly-{index + 1:02}.png"
    page.get_pixmap(matrix=pymupdf.Matrix(1.2, 1.2)).save(path)
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                box = pymupdf.Rect(span["bbox"])
                assert box.x0 >= -1 and box.y0 >= -1 and box.x1 <= page.rect.width + 1 and box.y1 <= page.rect.height + 1, span["text"]
    thumbnail = Image.open(path).convert("RGB")
    thumbnail.thumbnail((700, 500))
    tile = Image.new("RGB", (730, 540), "#e7edf4")
    tile.paste(thumbnail, ((730 - thumbnail.width) // 2, 25))
    ImageDraw.Draw(tile).text((12, 6), f"Workbook page {index + 1}", fill="black")
    tiles.append(tile)
montage = Image.new("RGB", (1460, 540 * ((len(tiles) + 1) // 2)), "white")
for index, tile in enumerate(tiles):
    montage.paste(tile, ((index % 2) * 730, (index // 2) * 540))
montage.save(previews / "workbook-contact.png")
(root / "visual-proof.json").write_text(json.dumps({"native_workbook_pages": len(document), "all_four_sheets_rendered": True,
    "chart_title_rendered": True, "text_within_page": True}, indent=2) + "\n")
