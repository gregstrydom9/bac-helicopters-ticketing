#!/usr/bin/env python3
"""
Create placeholder assets for testing:
- Logo image (white text on transparent background)
- Dangerous Goods PDF
"""

from pathlib import Path
import io

def create_placeholder_logo():
    """Create a simple placeholder logo PNG."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("PIL not installed, skipping logo creation")
        return

    # Create image with transparency
    width, height = 400, 150
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw white text (for dark background usage)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except:
        font = ImageFont.load_default()
        small_font = font

    # Main text
    draw.text((20, 30), "BAC", fill='white', font=font)
    draw.text((20, 80), "HELICOPTERS", fill='white', font=small_font)

    # Simple helicopter icon (basic shape)
    # Rotor
    draw.ellipse([280, 40, 380, 60], outline='white', width=2)
    draw.line([330, 50, 330, 80], fill='white', width=2)
    # Body
    draw.ellipse([300, 70, 360, 110], outline='white', width=2)
    # Tail
    draw.line([360, 90, 390, 90], fill='white', width=2)
    draw.polygon([(385, 80), (395, 90), (385, 100)], outline='white')

    # Save
    output_path = Path(__file__).parent / "logo.png"
    img.save(output_path, "PNG")
    print(f"Created placeholder logo: {output_path}")


def create_placeholder_dg_pdf():
    """Create a simple Dangerous Goods information PDF."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, ListFlowable, ListItem
        from reportlab.lib.colors import HexColor, black
        from reportlab.lib.units import mm
    except ImportError:
        print("ReportLab not installed, skipping DG PDF creation")
        return

    output_path = Path(__file__).parent / "docs" / "dg.pdf"
    output_path.parent.mkdir(exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=20*mm,
        rightMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=HexColor("#1a365d"),
        spaceAfter=12
    )
    heading_style = ParagraphStyle(
        'Heading',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=HexColor("#c53030"),
        spaceBefore=12,
        spaceAfter=6
    )
    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=8
    )
    bullet_style = ParagraphStyle(
        'Bullet',
        parent=styles['Normal'],
        fontSize=10,
        leftIndent=20,
        spaceAfter=4
    )

    content = []

    # Title
    content.append(Paragraph("DANGEROUS GOODS INFORMATION", title_style))
    content.append(Paragraph("BAC Helicopters - Passenger Advisory", styles['Normal']))
    content.append(Spacer(1, 20))

    # Introduction
    content.append(Paragraph(
        "For the safety of all passengers and crew, certain items are prohibited from being carried on aircraft. "
        "Please review this information carefully before your flight.",
        body_style
    ))

    # Prohibited Items
    content.append(Paragraph("PROHIBITED ITEMS", heading_style))
    content.append(Paragraph(
        "The following items are strictly prohibited in both carry-on and checked baggage:",
        body_style
    ))

    prohibited_items = [
        ["Category", "Examples"],
        ["Explosives", "Fireworks, flares, ammunition, blasting caps"],
        ["Compressed Gases", "Aerosols (non-toiletry), gas cylinders, fire extinguishers"],
        ["Flammable Liquids", "Petrol, lighter fluid, paints, solvents"],
        ["Flammable Solids", "Matches (strike-anywhere), magnesium, self-heating substances"],
        ["Oxidizers", "Bleach, pool chemicals, fertilizers"],
        ["Toxic Substances", "Pesticides, poisons, infectious substances"],
        ["Radioactive Materials", "Any radioactive substance or item"],
        ["Corrosives", "Car batteries, acids, alkalis, mercury"],
        ["Magnetic Materials", "Strong magnets that may affect aircraft instruments"],
    ]

    table = Table(prohibited_items, colWidths=[120, 350])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor("#1a365d")),
        ('TEXTCOLOR', (0, 0), (-1, 0), HexColor("#ffffff")),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor("#cccccc")),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    content.append(table)
    content.append(Spacer(1, 15))

    # Lithium Batteries
    content.append(Paragraph("LITHIUM BATTERIES", heading_style))
    content.append(Paragraph(
        "Lithium batteries present a fire risk if damaged, defective, or overheated. The following rules apply:",
        body_style
    ))
    content.append(Paragraph("- Spare lithium batteries must be carried in carry-on baggage only", bullet_style))
    content.append(Paragraph("- Batteries must be protected from short circuit (original packaging or tape over terminals)", bullet_style))
    content.append(Paragraph("- Power banks are treated as spare batteries", bullet_style))
    content.append(Paragraph("- Devices containing lithium batteries should be switched off during flight", bullet_style))

    # Declaration
    content.append(Paragraph("PASSENGER DECLARATION", heading_style))
    content.append(Paragraph(
        "By checking the acknowledgment box on the ticket form, you confirm that:",
        body_style
    ))
    content.append(Paragraph("- You have read and understood this dangerous goods information", bullet_style))
    content.append(Paragraph("- Your baggage does not contain any prohibited items", bullet_style))
    content.append(Paragraph("- You have not accepted items from unknown persons", bullet_style))
    content.append(Paragraph("- You understand that carrying prohibited items is a criminal offense", bullet_style))

    # Contact
    content.append(Spacer(1, 20))
    content.append(Paragraph(
        "If you have any questions about whether an item is permitted, please contact BAC Helicopters staff before your flight.",
        ParagraphStyle('Contact', parent=styles['Normal'], fontSize=9, textColor=HexColor("#666666"))
    ))

    doc.build(content)
    print(f"Created placeholder DG PDF: {output_path}")


if __name__ == '__main__':
    create_placeholder_logo()
    create_placeholder_dg_pdf()
    print("Done creating placeholder assets")
