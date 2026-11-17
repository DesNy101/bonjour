import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

ORANGE = colors.HexColor("#ff6600")
INK = colors.HexColor("#252321")
LINE = colors.HexColor("#e8e3de")


def _styles():
    ss = getSampleStyleSheet()
    return {"title": ParagraphStyle("t", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=18, textColor=INK, alignment=0, spaceAfter=2),
            "sub": ParagraphStyle("s", parent=ss["Normal"], fontSize=9, textColor=colors.HexColor("#6b6661"), spaceAfter=8),
            "cell": ParagraphStyle("c", parent=ss["Normal"], fontSize=8, leading=10),
            "norm": ss["Normal"]}


def _fmt(v):
    return "" if v is None else str(v)


def table_pdf(title: str, subtitle: str, columns: list[str], rows: list[list], business: str = "Bonjour Bakery", wide: bool = True) -> bytes:
    buf = io.BytesIO()
    page = landscape(A4) if wide or len(columns) > 6 else A4
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=title, author=business)
    st = _styles()
    story = [Paragraph(f"<font color='#ff6600'>{business.upper()}</font>", st["sub"]), Paragraph(title, st["title"]), Paragraph(subtitle, st["sub"])]
    data = [[Paragraph(f"<b>{c}</b>", st["cell"]) for c in columns]] + [[Paragraph(_fmt(c).replace("&", "&amp;").replace("<", "&lt;"), st["cell"]) for c in r] for r in rows]
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fff1e6")), ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#faf9f7")]),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story.append(t)
    doc.build(story)
    return buf.getvalue()


def document_pdf(kind: str, business: dict, order: dict) -> bytes:
    """Receipt / invoice for one order."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"{kind.title()} {order['order_number']}")
    st = _styles()
    naira = lambda k: f"NGN {k / 100:,.2f}"  # noqa  (Helvetica lacks the naira glyph)
    story = [Paragraph(f"<font color='#ff6600'><b>{business['name'].upper()}</b></font>", st["title"]),
             Paragraph(f"{business.get('address', '')}<br/>{business.get('phone', '')} {business.get('email', '')}", st["sub"]),
             Paragraph(f"<b>{kind.upper()}</b> &nbsp; {order['order_number']}", st["norm"]), Spacer(1, 4),
             Paragraph(f"Date: {order['created_at'][:10]} &nbsp;&nbsp; Branch: {order['branch']} &nbsp;&nbsp; Status: {order['status'].replace('_', ' ').title()}", st["sub"]),
             Paragraph(f"<b>Customer:</b> {order['contact_name']} {order['contact_phone']}<br/>"
                       f"<b>{order['order_type'].title()}</b>{(': ' + order['delivery_address']) if order['delivery_address'] else ''}", st["norm"]), Spacer(1, 8)]
    rows = [["Item", "Qty", "Unit price", "Total"]] + [[i["name"], i["quantity"], naira(i["unit_price_kobo"]), naira(i["line_total_kobo"])] for i in order["items"]]
    rows += [["", "", "Subtotal", naira(order["subtotal_kobo"])], ["", "", "Delivery", naira(order["delivery_fee_kobo"])]]
    if order["tax_kobo"]:
        rows.append(["", "", "Tax", naira(order["tax_kobo"])])
    rows += [["", "", "TOTAL", naira(order["total_kobo"])], ["", "", "Paid", naira(order["paid_kobo"])], ["", "", "Balance due", naira(order["balance_kobo"])]]
    t = Table(rows, colWidths=[85 * mm, 18 * mm, 35 * mm, 35 * mm])
    n = len(order["items"])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), ORANGE), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                           ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, n), 0.25, LINE),
                           ("FONTNAME", (2, n + 1 + (3 if order["tax_kobo"] else 2) - 1), (-1, n + 1 + (3 if order["tax_kobo"] else 2) - 1), "Helvetica-Bold")]))
    story.append(t)
    if kind == "invoice" and business.get("bank_account_number"):
        story += [Spacer(1, 12), Paragraph(f"<b>Pay by bank transfer:</b> {business.get('bank_name', '')} - {business['bank_account_number']} ({business.get('bank_account_name', '')}). Use {order['order_number']} as reference.", st["norm"])]
    story += [Spacer(1, 16), Paragraph("Thank you for choosing Bonjour Bakery.", st["sub"])]
    doc.build(story)
    return buf.getvalue()
