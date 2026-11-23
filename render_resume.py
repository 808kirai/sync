# turns resume.md into a one page a4 pdf, same layout every time
# format: "# name", contact lines, "## SECTION", "### title", "*date*", a plain stack line, "- " bullets
import re
import sys
from html import escape
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

grey = HexColor("#444444")
styles = {
    "name": ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=16, leading=19, alignment=TA_CENTER),
    "contact": ParagraphStyle("contact", fontName="Helvetica", fontSize=8.5, leading=10.5, alignment=TA_CENTER, textColor=grey),
    "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=10, leading=12, spaceBefore=6),
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=9, leading=11),
    "date": ParagraphStyle("date", fontName="Helvetica", fontSize=8.5, leading=11, alignment=2, textColor=grey),
    "stack": ParagraphStyle("stack", fontName="Helvetica-Oblique", fontSize=8.5, leading=10.5, textColor=grey),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=8.5, leading=10.5),
    # helvetica has no bullet glyph, the symbol font does
    "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=8.5, leading=10.5, leftIndent=9, bulletIndent=1,
                             bulletFontName="Symbol"),
}
page_width = A4[0] - 30 * mm


def inline(text):
    # escape first, then allow **bold**
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(text.strip(), quote=False))


def entry_header(title, date):
    row = [[Paragraph(inline(title), styles["title"]), Paragraph(inline(date), styles["date"])]]
    table = Table(row, colWidths=[page_width * 0.74, page_width * 0.26])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return table


def parse(md):
    story = []
    lines = [line.rstrip() for line in md.splitlines()]
    in_header = True
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip():
            continue
        if line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), styles["name"]))
        elif line.startswith("## "):
            in_header = False
            story.append(Paragraph(inline(line[3:]).upper(), styles["section"]))
            story.append(HRFlowable(width="100%", thickness=0.6, color=grey, spaceBefore=1, spaceAfter=2))
        elif line.startswith("### "):
            date = ""
            if i < len(lines) and re.fullmatch(r"\*[^*].*\*", lines[i].strip()):
                date = lines[i].strip()[1:-1]
                i += 1
            story.append(entry_header(line[4:], date))
            # a plain line straight after the header is the stack or role line
            if i < len(lines) and lines[i].strip() and not lines[i].startswith(("-", "#")):
                story.append(Paragraph(inline(lines[i]), styles["stack"]))
                i += 1
        elif line.startswith("- "):
            story.append(Paragraph(inline(line[2:]), styles["bullet"], bulletText="•"))
        else:
            story.append(Paragraph(inline(line), styles["contact" if in_header else "body"]))
    return story


def render(md_path, pdf_path):
    md_path, pdf_path = Path(md_path), Path(pdf_path)
    name = md_path.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm, title=f"{name} - Resume", author=name)
    doc.build(parse(md_path.read_text(encoding="utf-8")))
    return len(PdfReader(str(pdf_path)).pages)


if __name__ == "__main__":
    print(render(sys.argv[1], sys.argv[2]), "page(s)")
