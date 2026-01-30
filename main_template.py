"""
BAC Helicopters Passenger Ticketing System
Main Flask Application Template
Version: 1.1.0 - Updated branding and email functionality
"""

import os
import io
import csv
import base64
import smtplib
import zipfile
import logging
import re
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from urllib.parse import urlencode, quote

import qrcode
import requests
from flask import (
    Flask, render_template, request, jsonify, send_file,
    redirect, url_for, Response
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Paragraph, Frame
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# =============================================================================
# Configuration
# =============================================================================

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max request size

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Directories
BASE_DIR = Path(__file__).parent
TICKETS_DIR = BASE_DIR / "tickets"
MANIFEST_DIR = BASE_DIR / "manifest"
OUTBOX_DIR = BASE_DIR / "outbox"
DOCS_DIR = BASE_DIR / "docs"

# Ensure directories exist
TICKETS_DIR.mkdir(exist_ok=True)
MANIFEST_DIR.mkdir(exist_ok=True)
OUTBOX_DIR.mkdir(exist_ok=True)
DOCS_DIR.mkdir(exist_ok=True)

# Environment variables - accessed via functions to ensure fresh reads
def get_smtp_host():
    return os.environ.get("SMTP_HOST", "")

def get_smtp_port():
    return int(os.environ.get("SMTP_PORT", "587"))

def get_smtp_user():
    return os.environ.get("SMTP_USER", "")

def get_smtp_password():
    return os.environ.get("SMTP_PASSWORD", "")

def get_smtp_use_tls():
    return os.environ.get("SMTP_USE_TLS", "true").lower() == "true"

def get_from_email():
    return os.environ.get("FROM_EMAIL", "noreply@bachelicopters.com")

def get_pilot_email():
    return os.environ.get("PILOT_EMAIL", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")

# SharePoint config
MS_TENANT_ID = os.environ.get("MS_TENANT_ID", "")
MS_CLIENT_ID = os.environ.get("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = os.environ.get("MS_CLIENT_SECRET", "")
SP_DRIVE_ID = os.environ.get("SP_DRIVE_ID", "")
SP_BASE_FOLDER = os.environ.get("SP_BASE_FOLDER", "BAC-Ticketing")

# Admin key (simple auth)
ADMIN_KEY = "bac123"

# Base64 limits for validation
MAX_SINGLE_IMAGE_BASE64 = 800_000  # ~600KB binary
MAX_TOTAL_BASE64 = 1_200_000  # signature + photos

# =============================================================================
# Logo Loading (loads from file at runtime)
# =============================================================================

def get_logo_base64():
    """Load logo from file and return as base64."""
    logo_path = BASE_DIR / "logo.png"
    if logo_path.exists():
        try:
            logo_data = logo_path.read_bytes()
            return base64.b64encode(logo_data).decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to read logo: {e}")
    return None

def get_logo_bytes():
    """Load logo from file and return as bytes."""
    logo_path = BASE_DIR / "logo.png"
    if logo_path.exists():
        try:
            return logo_path.read_bytes()
        except Exception as e:
            logger.error(f"Failed to read logo: {e}")
    return None

# For backwards compatibility
BASE64_LOGO = get_logo_base64()

def write_embedded_logo():
    """Write logo status for verification on startup."""
    logo_path = BASE_DIR / "logo.png"
    if logo_path.exists():
        logger.info(f"Logo file found: {logo_path} ({logo_path.stat().st_size} bytes)")
    else:
        logger.warning(f"Logo file not found: {logo_path}")

# =============================================================================
# Conditions of Carriage Text
# =============================================================================

CONDITIONS_OF_CARRIAGE = """
CONDITIONS OF CARRIAGE

1. BAC Helicopters CC, hereafter referred to as the operator is a licensed air service operator and the holder of Air service license N1105D and G1106D issued in terms of the provisions of the Air Services Licensing act 1990 (Act 115 of 1990).

2. The operator warrants that it is insured in accordance with regulation 5 of the Domestic Air Service Regulations, 1991, as amended.

3. The operator, its servants, agents and representatives shall be under no liability for any damage of any kind, in excess of the limitations of the aforesaid regulations, whether caused or occasioned during the carriage of the passengers by air or in connection with the auxiliary incidental to the carriage by air or whether or not caused or occasioned by the act, omission, neglect, gross neglect or default of the operator's servants, agents or representatives.

4. The passenger herby indemnifies the operator against any claim or claims for compensation for damage, loss, injury, whether sustained on board the aircraft or in the course of the flight, embark or disembarking, caused directly or indirectly to his/her belongings which indemnity shall extend to the passenger's dependents, estate or any person whomsoever.

5. The operator indemnifies the passenger against any damage which the operator or its servants, agents or representatives may suffer through any act or omission of the passenger, however caused.

6. The operator undertakes to use its best efforts to carry the passenger and its baggage with reasonable dispatch.

7. The operator reserves the right to refuse the carriage to any person who has acquired a ticket in violation of the operator's tariffs, rules and regulations or has not signed a Passenger Indemnity form.

8. The conditions of carriage may not be altered, modified or amended or any provisions be waived by any servant, agent or representative of the operator.

Notice: If Passenger's journey involves an ultimate destination or stop in a country other than the country of departure, the provisions of the Warsaw Convention may be applicable. The Convention governs and in most cases limits the liability of operators for death and personal injury and the loss or damage of baggage.

THE PASSENGER BY ACCEPTANCE OF THIS TICKET ACCEPTS THE CONDITIONS OF CARRIAGE
"""

# =============================================================================
# Utility Functions
# =============================================================================

def get_base_url():
    """Get the base URL for generating links."""
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL.rstrip("/")
    return request.host_url.rstrip("/")


def slugify(text):
    """Convert text to URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text


def generate_flight_id(date, route, reg):
    """Generate a unique flight ID."""
    return f"{date}_{slugify(route)}_{slugify(reg)}"


def get_flight_dir(flight_id):
    """Get the ticket directory for a flight."""
    flight_dir = TICKETS_DIR / flight_id
    flight_dir.mkdir(exist_ok=True)
    return flight_dir


def decode_base64_image(data_url):
    """Decode a base64 data URL to bytes."""
    if not data_url:
        return None
    try:
        # Handle data URL format
        if ',' in data_url:
            header, data = data_url.split(',', 1)
        else:
            data = data_url
        return base64.b64decode(data)
    except Exception as e:
        logger.error(f"Failed to decode base64 image: {e}")
        return None


def generate_qr_code(url):
    """Generate a QR code as base64 PNG."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


# =============================================================================
# Ticket Number Counter
# =============================================================================

TICKET_COUNTER_FILE = BASE_DIR / "ticket_counter.txt"

def get_next_ticket_number():
    """Get the next sequential ticket number."""
    try:
        if TICKET_COUNTER_FILE.exists():
            current = int(TICKET_COUNTER_FILE.read_text().strip())
        else:
            current = 1548  # Starting number to match existing physical tickets

        next_num = current + 1
        TICKET_COUNTER_FILE.write_text(str(next_num))
        return next_num
    except Exception as e:
        logger.error(f"Error getting ticket number: {e}")
        # Fallback to timestamp-based number
        return int(datetime.now().strftime("%H%M%S"))


# =============================================================================
# CSV Manifest Functions
# =============================================================================

MANIFEST_COLUMNS = [
    'ticket_number', 'timestamp', 'name', 'body_weight', 'num_bags', 'bag_weight',
    'email', 'flight_date', 'flight_time', 'route', 'ac_type', 'registration',
    'pilot', 'dg_ack'
]


def append_to_manifest(flight_id, data):
    """Append a row to the flight manifest CSV."""
    manifest_path = MANIFEST_DIR / f"{flight_id}.csv"
    file_exists = manifest_path.exists()

    with open(manifest_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)

    return manifest_path


def read_manifest(flight_id):
    """Read all rows from a flight manifest."""
    manifest_path = MANIFEST_DIR / f"{flight_id}.csv"
    if not manifest_path.exists():
        return []

    with open(manifest_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return list(reader)


def get_all_flights():
    """Get all flight IDs from manifests and ticket directories."""
    flights = set()

    # From manifests
    for csv_file in MANIFEST_DIR.glob("*.csv"):
        flights.add(csv_file.stem)

    # From ticket directories
    for ticket_dir in TICKETS_DIR.iterdir():
        if ticket_dir.is_dir():
            flights.add(ticket_dir.name)

    return sorted(flights, reverse=True)


def get_flight_summary(flight_id):
    """Get summary statistics for a flight."""
    manifest = read_manifest(flight_id)
    flight_dir = TICKETS_DIR / flight_id
    ticket_count = len(list(flight_dir.glob("*.pdf"))) if flight_dir.exists() else 0

    total_body_weight = 0
    total_bag_weight = 0
    total_bags = 0

    for row in manifest:
        try:
            total_body_weight += float(row.get('body_weight', 0) or 0)
            total_bag_weight += float(row.get('bag_weight', 0) or 0)
            total_bags += int(row.get('num_bags', 0) or 0)
        except (ValueError, TypeError):
            pass

    # Extract flight info from first manifest row or flight_id
    flight_info = {}
    if manifest:
        flight_info = {
            'date': manifest[0].get('flight_date', ''),
            'time': manifest[0].get('flight_time', ''),
            'route': manifest[0].get('route', ''),
            'ac_type': manifest[0].get('ac_type', ''),
            'registration': manifest[0].get('registration', ''),
            'pilot': manifest[0].get('pilot', ''),
        }
    else:
        # Parse from flight_id
        parts = flight_id.split('_')
        if len(parts) >= 3:
            flight_info = {
                'date': parts[0],
                'route': parts[1].upper().replace('-', ' - '),
                'registration': parts[2].upper(),
            }

    return {
        'flight_id': flight_id,
        'passenger_count': len(manifest),
        'ticket_count': ticket_count,
        'total_body_weight': total_body_weight,
        'total_bag_weight': total_bag_weight,
        'total_bags': total_bags,
        **flight_info
    }


# =============================================================================
# PDF Generation
# =============================================================================

def create_ticket_pdf(data, signature_bytes, photo1_bytes, photo2_bytes):
    """
    Generate a clean, professional A4 PDF ticket matching BAC letterhead style.
    Returns the PDF as bytes.
    """
    buffer = io.BytesIO()
    width, height = A4
    c = canvas.Canvas(buffer, pagesize=A4)

    # Colors - clean professional palette matching letterhead
    brand_blue = HexColor("#1a5a8a")
    light_gray = HexColor("#f5f5f5")
    medium_gray = HexColor("#666666")
    border_gray = HexColor("#cccccc")
    red_accent = HexColor("#c41e3a")

    # Page margins
    page_margin = 12 * mm

    # ==========================================================================
    # Professional Border
    # ==========================================================================
    border_width = 1.5
    c.setStrokeColor(brand_blue)
    c.setLineWidth(border_width)
    c.rect(page_margin, page_margin, width - 2 * page_margin, height - 2 * page_margin, fill=0, stroke=1)

    # Inner subtle border
    c.setStrokeColor(border_gray)
    c.setLineWidth(0.5)
    inner_margin = page_margin + 3 * mm
    c.rect(inner_margin, inner_margin, width - 2 * inner_margin, height - 2 * inner_margin, fill=0, stroke=1)

    # Content area
    margin = page_margin + 8 * mm
    content_width = width - 2 * margin
    y = height - margin

    # ==========================================================================
    # Header - Logo and Title
    # ==========================================================================
    logo_data = get_logo_bytes()
    if logo_data:
        try:
            logo_reader = ImageReader(io.BytesIO(logo_data))
            logo_width = 50 * mm
            logo_height = 18 * mm
            c.drawImage(
                logo_reader,
                margin,
                y - logo_height,
                width=logo_width,
                height=logo_height,
                preserveAspectRatio=True,
                mask='auto'
            )
        except Exception as e:
            logger.error(f"Failed to draw logo: {e}")
            c.setFillColor(brand_blue)
            c.setFont("Helvetica-Bold", 16)
            c.drawString(margin, y - 12 * mm, "BAC HELICOPTERS")

    # Title on the right
    c.setFillColor(brand_blue)
    c.setFont("Helvetica-Bold", 18)
    c.drawRightString(width - margin, y - 6 * mm, "PASSENGER TICKET")

    # Underline
    c.setStrokeColor(brand_blue)
    c.setLineWidth(1)
    c.line(width - margin - 70 * mm, y - 9 * mm, width - margin, y - 9 * mm)

    # Ticket number
    c.setFillColor(red_accent)
    c.setFont("Helvetica-Bold", 14)
    ticket_num = data.get('ticket_number', 'N/A')
    c.drawRightString(width - margin, y - 16 * mm, f"Ticket #: {ticket_num}")

    y -= 26 * mm

    # ==========================================================================
    # Flight Details Section
    # ==========================================================================
    # Section divider line
    c.setStrokeColor(brand_blue)
    c.setLineWidth(0.75)
    c.line(margin, y, margin + content_width, y)
    y -= 6 * mm

    # Two-column layout for flight details
    col1_x = margin
    col2_x = margin + content_width / 2 + 5 * mm
    label_color = medium_gray
    value_color = black

    # Row 1: Name (full width)
    c.setFont("Helvetica", 9)
    c.setFillColor(label_color)
    c.drawString(col1_x, y, "Passenger Name")
    c.setFillColor(value_color)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(col1_x, y - 5 * mm, data.get('name', ''))
    y -= 14 * mm

    # Row 2: Date of Flight | ETD
    c.setFont("Helvetica", 9)
    c.setFillColor(label_color)
    c.drawString(col1_x, y, "Date of Flight")
    c.drawString(col2_x, y, "ETD")
    c.setFillColor(value_color)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(col1_x, y - 5 * mm, data.get('flight_date', ''))
    c.drawString(col2_x, y - 5 * mm, data.get('flight_time', ''))
    y -= 14 * mm

    # Row 3: Route | PIC
    c.setFont("Helvetica", 9)
    c.setFillColor(label_color)
    c.drawString(col1_x, y, "Route")
    c.drawString(col2_x, y, "PIC")
    c.setFillColor(value_color)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(col1_x, y - 5 * mm, data.get('route', ''))
    c.drawString(col2_x, y - 5 * mm, data.get('pilot', ''))
    y -= 14 * mm

    # Row 4: A/C Type | A/C Reg
    c.setFont("Helvetica", 9)
    c.setFillColor(label_color)
    c.drawString(col1_x, y, "A/C Type")
    c.drawString(col2_x, y, "A/C Reg")
    c.setFillColor(value_color)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(col1_x, y - 5 * mm, data.get('ac_type', ''))
    c.drawString(col2_x, y - 5 * mm, data.get('registration', ''))
    y -= 16 * mm

    # ==========================================================================
    # Weight Declaration Section
    # ==========================================================================
    c.setStrokeColor(brand_blue)
    c.setLineWidth(0.75)
    c.line(margin, y, margin + content_width, y)
    y -= 5 * mm

    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(brand_blue)
    c.drawString(margin, y, "WEIGHT DECLARATION")
    y -= 8 * mm

    # Weight boxes - clean design
    box_width = (content_width - 10 * mm) / 3
    box_height = 18 * mm

    for i, (label, value) in enumerate([
        ("WEIGHT OF PAX", f"{data.get('body_weight', '')} kg"),
        ("NO OF BAG ITEMS", f"{data.get('num_bags', '0')}"),
        ("WEIGHT OF BAG", f"{data.get('bag_weight', '0')} kg")
    ]):
        box_x = margin + i * (box_width + 5 * mm)

        # Light background
        c.setFillColor(light_gray)
        c.roundRect(box_x, y - box_height, box_width, box_height, 3, fill=1, stroke=0)

        # Border
        c.setStrokeColor(border_gray)
        c.setLineWidth(0.5)
        c.roundRect(box_x, y - box_height, box_width, box_height, 3, fill=0, stroke=1)

        # Label
        c.setFont("Helvetica", 7)
        c.setFillColor(medium_gray)
        c.drawCentredString(box_x + box_width/2, y - 5 * mm, label)

        # Value
        c.setFont("Helvetica-Bold", 14)
        c.setFillColor(black)
        c.drawCentredString(box_x + box_width/2, y - 13 * mm, value)

    y -= box_height + 4 * mm

    c.setFont("Helvetica-Oblique", 7)
    c.setFillColor(medium_gray)
    c.drawString(margin, y, "Weights declared by passenger. To be verified at check-in.")
    y -= 10 * mm

    # ==========================================================================
    # Signature Section
    # ==========================================================================
    c.setStrokeColor(brand_blue)
    c.setLineWidth(0.75)
    c.line(margin, y, margin + content_width, y)
    y -= 5 * mm

    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(brand_blue)
    c.drawString(margin, y, "PASSENGER SIGNATURE")
    y -= 4 * mm

    sig_width = 70 * mm
    sig_height = 25 * mm

    if signature_bytes:
        try:
            sig_reader = ImageReader(io.BytesIO(signature_bytes))
            c.drawImage(
                sig_reader,
                margin,
                y - sig_height,
                width=sig_width,
                height=sig_height,
                preserveAspectRatio=True
            )
        except Exception as e:
            logger.error(f"Failed to draw signature: {e}")

    # Signature line
    c.setStrokeColor(black)
    c.setLineWidth(0.5)
    c.line(margin, y - sig_height - 1 * mm, margin + sig_width, y - sig_height - 1 * mm)

    # Info next to signature
    c.setFont("Helvetica", 8)
    c.setFillColor(medium_gray)
    info_x = margin + sig_width + 10 * mm
    info_y = y - 3 * mm

    c.drawString(info_x, info_y, f"Date: {data.get('timestamp', '').split(' ')[0] if data.get('timestamp') else ''}")
    info_y -= 5 * mm
    c.drawString(info_x, info_y, f"Email: {data.get('email', '')}")
    info_y -= 5 * mm
    dg_ack = "Yes" if data.get('dg_ack') == 'True' else "No"
    c.drawString(info_x, info_y, f"DG Acknowledged: {dg_ack}")
    info_y -= 5 * mm
    c.drawString(info_x, info_y, "Conditions Accepted: Yes")

    y -= sig_height + 10 * mm

    # ==========================================================================
    # Acceptance Banner
    # ==========================================================================
    banner_height = 8 * mm
    c.setFillColor(brand_blue)
    c.roundRect(margin, y - banner_height, content_width, banner_height, 2, fill=1, stroke=0)

    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(width / 2, y - 5.5 * mm, "THE PASSENGER BY ACCEPTANCE OF THIS TICKET ACCEPTS THE CONDITIONS OF CARRIAGE")

    y -= banner_height + 8 * mm

    # ==========================================================================
    # Conditions of Carriage (compact two-column)
    # ==========================================================================
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(brand_blue)
    c.drawString(margin, y, "CONDITIONS OF CARRIAGE")
    y -= 4 * mm

    # Calculate remaining space
    dg_height = 28 * mm
    footer_height = 10 * mm
    conditions_height = y - inner_margin - dg_height - footer_height

    styles = getSampleStyleSheet()
    cond_style = ParagraphStyle(
        'Conditions',
        parent=styles['Normal'],
        fontSize=5.5,
        leading=6.5,
        textColor=medium_gray,
    )

    # Two columns for conditions
    lines = CONDITIONS_OF_CARRIAGE.strip().split('\n')
    mid = len(lines) // 2
    col1_text = '<br/>'.join(lines[:mid])
    col2_text = '<br/>'.join(lines[mid:])

    col_width = (content_width - 6 * mm) / 2

    col1_para = Paragraph(col1_text, cond_style)
    col2_para = Paragraph(col2_text, cond_style)

    frame1 = Frame(margin, y - conditions_height, col_width, conditions_height,
                   leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    frame2 = Frame(margin + col_width + 6 * mm, y - conditions_height, col_width, conditions_height,
                   leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

    frame1.addFromList([col1_para], c)
    frame2.addFromList([col2_para], c)

    y -= conditions_height + 4 * mm

    # ==========================================================================
    # Dangerous Goods Notice (compact)
    # ==========================================================================
    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(brand_blue)
    c.drawString(margin, y, "DANGEROUS GOODS NOT PERMITTED")
    y -= 3 * mm

    c.setFont("Helvetica", 6)
    c.setFillColor(medium_gray)
    dg_text = "Explosives • Compressed Gases • Flammable Liquids/Solids • Corrosives • Oxidizers • Poisons • Radioactive Materials • Lithium Batteries (checked baggage)"
    c.drawString(margin, y, dg_text)
    y -= 4 * mm
    c.drawString(margin, y, "Medicines and toiletries in limited quantities permitted. Full DG information provided separately.")

    # ==========================================================================
    # Footer
    # ==========================================================================
    footer_y = inner_margin + 4 * mm
    c.setFont("Helvetica", 6)
    c.setFillColor(medium_gray)
    c.drawCentredString(width / 2, footer_y, "BAC Helicopters CC  •  Air Service License N1105D & G1106D  •  This ticket is valid only for the flight shown above")

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


# =============================================================================
# Email Functions
# =============================================================================

def is_smtp_configured():
    """Check if SMTP is configured."""
    return bool(get_smtp_host() and get_smtp_user() and get_smtp_password())


def send_email(to_emails, subject, body, attachments=None):
    """
    Send an email with optional attachments.
    If SMTP not configured, save as .eml file.

    attachments: list of (filename, bytes, mimetype) tuples
    """
    msg = MIMEMultipart()
    msg['From'] = get_from_email()
    msg['To'] = ', '.join(to_emails) if isinstance(to_emails, list) else to_emails
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    if attachments:
        for filename, data, mimetype in attachments:
            part = MIMEBase(*mimetype.split('/'))
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(part)

    if is_smtp_configured():
        smtp_host = get_smtp_host()
        smtp_port = get_smtp_port()
        smtp_user = get_smtp_user()
        smtp_password = get_smtp_password()
        smtp_use_tls = get_smtp_use_tls()

        try:
            logger.info(f"Connecting to SMTP: {smtp_host}:{smtp_port}")
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                logger.info("SMTP connected, starting TLS...")
                if smtp_use_tls:
                    server.starttls()
                logger.info(f"Logging in as {smtp_user}...")
                server.login(smtp_user, smtp_password)
                logger.info("Login successful, sending message...")
                server.send_message(msg)
            logger.info(f"Email sent successfully to {to_emails}")
            return True
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP Authentication failed: {e}")
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
        except Exception as e:
            logger.error(f"Failed to send email: {type(e).__name__}: {e}")
            # Fall through to save as .eml

    # Save as .eml file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = slugify(subject)[:30]
    eml_path = OUTBOX_DIR / f"{timestamp}_{slug}.eml"
    eml_path.write_bytes(msg.as_bytes())
    logger.info(f"Email saved to {eml_path}")
    return False


def send_passenger_email(passenger_data, ticket_pdf_bytes):
    """Send ticket email to passenger."""
    emails = [e.strip() for e in passenger_data['email'].split(',') if e.strip()]

    subject = f"Your BAC Helicopters Ticket — {passenger_data['flight_date']} {passenger_data['route']} ({passenger_data['registration']})"

    body = f"""Dear {passenger_data['name']},

Thank you for choosing BAC Helicopters.

Please find attached your ticket for the following flight:

Date: {passenger_data['flight_date']}
Time: {passenger_data['flight_time']}
Route: {passenger_data['route']}
Aircraft: {passenger_data['registration']}
Pilot: {passenger_data['pilot']}

Also attached is the Dangerous Goods information sheet for your reference.

Please arrive at the designated check-in location at least 15 minutes before your scheduled departure time.

Safe travels!

BAC Helicopters
"""

    attachments = [
        (f"ticket_{passenger_data['name'].replace(' ', '_')}.pdf", ticket_pdf_bytes, "application/pdf")
    ]

    # Attach DG PDF if available
    dg_pdf_path = DOCS_DIR / "dg.pdf"
    if dg_pdf_path.exists():
        attachments.append(
            ("Dangerous_Goods_Information.pdf", dg_pdf_path.read_bytes(), "application/pdf")
        )

    send_email(emails, subject, body, attachments)


def send_pilot_email(flight_id, flight_summary):
    """Send manifest summary to pilot with all tickets - sends update each time a passenger registers."""
    pilot_email = get_pilot_email()
    if not pilot_email:
        logger.warning("PILOT_EMAIL not configured, skipping pilot notification")
        return

    manifest = read_manifest(flight_id)
    passenger_count = len(manifest)

    # Calculate total weights
    total_pax_weight = sum(float(row.get('body_weight', 0) or 0) for row in manifest)
    total_bag_weight = sum(float(row.get('bag_weight', 0) or 0) for row in manifest)
    total_bags = sum(int(row.get('num_bags', 0) or 0) for row in manifest)
    total_weight = total_pax_weight + total_bag_weight

    subject = f"[MANIFEST UPDATE] {flight_summary.get('route', flight_id)} - {flight_summary.get('date', 'N/A')} - {passenger_count} PAX"

    body = f"""═══════════════════════════════════════════════════════════════
                    PASSENGER AND CARGO MANIFEST
                         BAC HELICOPTERS CC
═══════════════════════════════════════════════════════════════

FLIGHT DETAILS
──────────────────────────────────────────────────────────────
A/CRAFT REG:    {flight_summary.get('registration', 'N/A')}
A/C TYPE:       {flight_summary.get('ac_type', 'N/A')}
PIC:            {flight_summary.get('pilot', 'N/A')}
DATE:           {flight_summary.get('date', 'N/A')}
ETD:            {flight_summary.get('time', 'N/A')}
ROUTING:        {flight_summary.get('route', 'N/A')}

═══════════════════════════════════════════════════════════════
                      WEIGHT SUMMARY
═══════════════════════════════════════════════════════════════
PASSENGERS:           {passenger_count}
TOTAL PAX WEIGHT:     {total_pax_weight:.1f} kg
TOTAL BAG ITEMS:      {total_bags}
TOTAL BAG WEIGHT:     {total_bag_weight:.1f} kg
────────────────────────────────────
TOTAL WEIGHT:         {total_weight:.1f} kg
═══════════════════════════════════════════════════════════════

PASSENGER LIST
──────────────────────────────────────────────────────────────
"""

    # Build passenger table
    body += f"{'#':<3} {'NAME':<25} {'PAX WT':<10} {'BAGS':<6} {'BAG WT':<10} {'DG ACK':<8}\n"
    body += "─" * 66 + "\n"

    for i, row in enumerate(manifest, 1):
        name = row.get('name', 'Unknown')[:24]
        pax_wt = f"{row.get('body_weight', 'N/A')} kg"
        bags = row.get('num_bags', '0')
        bag_wt = f"{row.get('bag_weight', '0')} kg"
        dg_ack = "YES" if row.get('dg_ack') == 'True' else "NO"
        body += f"{i:<3} {name:<25} {pax_wt:<10} {bags:<6} {bag_wt:<10} {dg_ack:<8}\n"

    body += "─" * 66 + "\n"
    body += f"{'TOTALS:':<29} {total_pax_weight:<10.1f} {total_bags:<6} {total_bag_weight:<10.1f}\n"

    body += f"""
═══════════════════════════════════════════════════════════════

NOTE: This manifest updates automatically each time a passenger
completes their registration. The attached ZIP contains all
passenger tickets received so far.

All passengers have acknowledged Dangerous Goods restrictions
and accepted the Conditions of Carriage.

──────────────────────────────────────────────────────────────
Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
BAC Helicopters CC - Air Service License N1105D & G1106D
"""

    # Collect all tickets for this flight
    attachments = []
    flight_dir = TICKETS_DIR / flight_id
    if flight_dir.exists():
        # Create a ZIP of all tickets
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for pdf_file in flight_dir.glob("*.pdf"):
                zf.writestr(pdf_file.name, pdf_file.read_bytes())
        zip_buffer.seek(0)
        attachments.append((f"manifest_{flight_id}_tickets.zip", zip_buffer.getvalue(), "application/zip"))

    # Also attach the CSV manifest
    manifest_path = MANIFEST_DIR / f"{flight_id}.csv"
    if manifest_path.exists():
        attachments.append((f"manifest_{flight_id}.csv", manifest_path.read_bytes(), "text/csv"))

    logger.info(f"Sending pilot manifest update for {flight_id} to {pilot_email}")
    send_email([pilot_email], subject, body, attachments)


# =============================================================================
# SharePoint Functions
# =============================================================================

def get_sharepoint_token():
    """Get OAuth token for SharePoint."""
    if not all([MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET]):
        return None

    token_url = f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token"
    data = {
        'client_id': MS_CLIENT_ID,
        'client_secret': MS_CLIENT_SECRET,
        'scope': 'https://graph.microsoft.com/.default',
        'grant_type': 'client_credentials'
    }

    try:
        resp = requests.post(token_url, data=data)
        resp.raise_for_status()
        return resp.json().get('access_token')
    except Exception as e:
        logger.error(f"Failed to get SharePoint token: {e}")
        return None


def ensure_sharepoint_folder(token, folder_path):
    """Ensure a folder exists in SharePoint."""
    url = f"https://graph.microsoft.com/v1.0/drives/{SP_DRIVE_ID}/root:/{folder_path}"
    headers = {'Authorization': f'Bearer {token}'}

    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return True

    # Create folder
    parent_path = '/'.join(folder_path.split('/')[:-1])
    folder_name = folder_path.split('/')[-1]

    create_url = f"https://graph.microsoft.com/v1.0/drives/{SP_DRIVE_ID}/root:/{parent_path}:/children"
    data = {
        'name': folder_name,
        'folder': {},
        '@microsoft.graph.conflictBehavior': 'fail'
    }

    try:
        resp = requests.post(create_url, headers=headers, json=data)
        return resp.status_code in [200, 201, 409]  # 409 = already exists
    except Exception as e:
        logger.error(f"Failed to create SharePoint folder: {e}")
        return False


def upload_to_sharepoint(file_path, file_bytes, flight_date):
    """Upload a file to SharePoint."""
    token = get_sharepoint_token()
    if not token:
        return False

    folder_path = f"{SP_BASE_FOLDER}/{flight_date}"
    ensure_sharepoint_folder(token, SP_BASE_FOLDER)
    ensure_sharepoint_folder(token, folder_path)

    upload_url = f"https://graph.microsoft.com/v1.0/drives/{SP_DRIVE_ID}/root:/{folder_path}/{file_path}:/content"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/octet-stream'
    }

    try:
        resp = requests.put(upload_url, headers=headers, data=file_bytes)
        if resp.status_code in [200, 201]:
            logger.info(f"Uploaded {file_path} to SharePoint")
            return True
        else:
            logger.error(f"SharePoint upload failed: {resp.status_code} {resp.text}")
            # Log to error file
            error_log = OUTBOX_DIR / "sharepoint_upload_errors.log"
            with open(error_log, 'a') as f:
                f.write(f"{datetime.now()}: {file_path} - {resp.status_code} {resp.text}\n")
            return False
    except Exception as e:
        logger.error(f"SharePoint upload exception: {e}")
        error_log = OUTBOX_DIR / "sharepoint_upload_errors.log"
        with open(error_log, 'a') as f:
            f.write(f"{datetime.now()}: {file_path} - {e}\n")
        return False


# =============================================================================
# Flask Routes
# =============================================================================

@app.route('/healthz')
def healthz():
    """Health check endpoint."""
    return 'ok', 200


@app.route('/debug/logo')
def debug_logo():
    """Debug endpoint to view the logo."""
    logo_bytes = get_logo_bytes()
    if not logo_bytes:
        logo_path = BASE_DIR / "logo.png"
        return f"No logo found at {logo_path}", 404

    return Response(logo_bytes, mimetype='image/png')


@app.route('/debug/smtp')
def debug_smtp():
    """Debug endpoint to check SMTP configuration."""
    smtp_user = get_smtp_user()
    smtp_password = get_smtp_password()
    info = {
        'smtp_configured': is_smtp_configured(),
        'smtp_host': get_smtp_host() or '(not set)',
        'smtp_port': get_smtp_port(),
        'smtp_user': smtp_user[:3] + '***' if smtp_user else '(not set)',
        'smtp_password': '***' if smtp_password else '(not set)',
        'smtp_password_length': len(smtp_password) if smtp_password else 0,
        'from_email': get_from_email() or '(not set)',
        'smtp_use_tls': get_smtp_use_tls(),
        'pilot_email': get_pilot_email() or '(not set)',
    }
    return jsonify(info)


@app.route('/debug/test_email')
def test_email():
    """Send a test email to verify SMTP is working."""
    test_to = request.args.get('to', '')
    if not test_to:
        return jsonify({'error': 'Please provide ?to=email@example.com'}), 400

    if not is_smtp_configured():
        return jsonify({'error': 'SMTP not configured'}), 400

    subject = "BAC Helicopters - Test Email"
    body = f"""This is a test email from BAC Helicopters Ticketing System.

If you received this, email sending is working correctly!

Sent at: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
"""

    try:
        result = send_email([test_to], subject, body)
        if result:
            return jsonify({'success': True, 'message': f'Test email sent to {test_to}'})
        else:
            return jsonify({'success': False, 'message': 'Email saved to outbox (SMTP failed)'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/docs/dg')
def serve_dg_pdf():
    """Serve the Dangerous Goods PDF."""
    dg_path = DOCS_DIR / "dg.pdf"
    if not dg_path.exists():
        return "Dangerous Goods PDF not found. Please upload dg.pdf to the docs folder.", 404

    return send_file(dg_path, mimetype='application/pdf')


@app.route('/')
def passenger_form():
    """Render the passenger form."""
    return render_template(
        'index.html',
        flight_date=request.args.get('date', ''),
        flight_time=request.args.get('time', ''),
        route=request.args.get('route', ''),
        ac_type=request.args.get('ac_type', ''),
        registration=request.args.get('reg', ''),
        pilot=request.args.get('pilot', ''),
        conditions=CONDITIONS_OF_CARRIAGE
    )


@app.route('/submit', methods=['POST'])
def submit_ticket():
    """Handle passenger ticket submission."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Validate required fields
        required = ['name', 'email', 'body_weight', 'flight_date', 'route', 'registration']
        for field in required:
            if not data.get(field):
                return jsonify({'error': f'Missing required field: {field}'}), 400

        # Validate acknowledgments
        if not data.get('dg_acknowledged'):
            return jsonify({'error': 'You must acknowledge the Dangerous Goods information'}), 400

        if not data.get('conditions_accepted'):
            return jsonify({'error': 'You must accept the Conditions of Carriage'}), 400

        if not data.get('signature_data'):
            return jsonify({'error': 'Signature is required'}), 400

        # Validate base64 sizes
        signature_data = data.get('signature_data', '')
        photo1_data = data.get('photo1_data', '')
        photo2_data = data.get('photo2_data', '')

        for name, img_data in [('signature', signature_data), ('photo1', photo1_data), ('photo2', photo2_data)]:
            if img_data and len(img_data) > MAX_SINGLE_IMAGE_BASE64:
                return jsonify({'error': f'{name} image is too large. Please use a smaller image.'}), 400

        total_base64 = len(signature_data) + len(photo1_data) + len(photo2_data)
        if total_base64 > MAX_TOTAL_BASE64:
            return jsonify({'error': 'Total image data is too large. Please use smaller images.'}), 400

        # Decode images
        signature_bytes = decode_base64_image(signature_data)
        photo1_bytes = decode_base64_image(photo1_data) if photo1_data else None
        photo2_bytes = decode_base64_image(photo2_data) if photo2_data else None

        # Generate timestamp
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        timestamp_file = now.strftime("%Y%m%d_%H%M%S")

        # Prepare passenger data
        passenger_data = {
            'timestamp': timestamp,
            'name': data.get('name', '').strip(),
            'email': data.get('email', '').strip(),
            'body_weight': data.get('body_weight', ''),
            'num_bags': data.get('num_bags', '0'),
            'bag_weight': data.get('bag_weight', '0'),
            'flight_date': data.get('flight_date', ''),
            'flight_time': data.get('flight_time', ''),
            'route': data.get('route', ''),
            'ac_type': data.get('ac_type', ''),
            'registration': data.get('registration', ''),
            'pilot': data.get('pilot', ''),
            'dg_ack': str(data.get('dg_acknowledged', False)),
        }

        # Generate ticket number
        ticket_number = get_next_ticket_number()
        passenger_data['ticket_number'] = str(ticket_number)

        # Generate flight ID
        flight_id = generate_flight_id(
            passenger_data['flight_date'],
            passenger_data['route'],
            passenger_data['registration']
        )

        # Create ticket PDF
        ticket_pdf = create_ticket_pdf(passenger_data, signature_bytes, photo1_bytes, photo2_bytes)

        # Save ticket PDF
        flight_dir = get_flight_dir(flight_id)
        name_slug = slugify(passenger_data['name'])
        ticket_filename = f"ticket_{timestamp_file}_{name_slug}.pdf"
        ticket_path = flight_dir / ticket_filename
        ticket_path.write_bytes(ticket_pdf)
        logger.info(f"Ticket saved to {ticket_path}")

        # Append to manifest
        append_to_manifest(flight_id, passenger_data)

        # Send passenger email
        send_passenger_email(passenger_data, ticket_pdf)

        # Send pilot email
        flight_summary = get_flight_summary(flight_id)
        send_pilot_email(flight_id, flight_summary)

        # Upload to SharePoint (optional)
        if SP_DRIVE_ID:
            upload_to_sharepoint(ticket_filename, ticket_pdf, passenger_data['flight_date'])
            manifest_path = MANIFEST_DIR / f"{flight_id}.csv"
            if manifest_path.exists():
                upload_to_sharepoint(f"{flight_id}.csv", manifest_path.read_bytes(), passenger_data['flight_date'])

        return jsonify({
            'success': True,
            'message': 'Ticket submitted successfully! Check your email for confirmation.',
            'ticket_id': ticket_filename
        })

    except Exception as e:
        logger.exception("Error processing ticket submission")
        return jsonify({'error': f'Server error: {str(e)}'}), 500


@app.route('/admin')
def admin_dashboard():
    """Render the admin dashboard."""
    key = request.args.get('key', '')
    if key != ADMIN_KEY:
        return render_template('admin.html', authorized=False, flights=[])

    flights = []
    for flight_id in get_all_flights():
        flights.append(get_flight_summary(flight_id))

    return render_template('admin.html', authorized=True, flights=flights, admin_key=ADMIN_KEY)


@app.route('/admin/create_link', methods=['POST'])
def create_link():
    """Create a shareable link and QR code for a flight."""
    key = request.form.get('key', '')
    if key != ADMIN_KEY:
        return jsonify({'error': 'Unauthorized'}), 401

    # Get flight details
    flight_date = request.form.get('date', '').strip()
    flight_time = request.form.get('time', '').strip()
    route = request.form.get('route', '').strip()
    ac_type = request.form.get('ac_type', '').strip()
    registration = request.form.get('reg', '').strip()
    pilot = request.form.get('pilot', '').strip()
    recipient_emails = request.form.get('emails', '').strip()

    # Validate
    if not all([flight_date, flight_time, route, registration, pilot]):
        return jsonify({'error': 'All flight details are required'}), 400

    # Build URL
    base_url = get_base_url()
    params = {
        'date': flight_date,
        'time': flight_time,
        'route': route,
        'ac_type': ac_type,
        'reg': registration,
        'pilot': pilot
    }
    share_url = f"{base_url}/?{urlencode(params)}"

    # Generate QR code
    qr_base64 = generate_qr_code(share_url)

    # Send emails if provided
    if recipient_emails:
        emails = [e.strip() for e in re.split(r'[,;]', recipient_emails) if e.strip()]
        if emails:
            logger.info(f"Sending flight link to {len(emails)} recipients...")
            subject = f"BAC Helicopters Flight Link — {flight_date} {route}"
            body = f"""Hello,

You have been sent a flight booking link for BAC Helicopters.

Flight Details:
Date: {flight_date}
ETD: {flight_time}
Route: {route}
A/C Type: {ac_type}
A/C Reg: {registration}
PIC: {pilot}

Click the link below or scan the attached QR code to complete your ticket:
{share_url}

Thank you,
BAC Helicopters
"""
            qr_bytes = base64.b64decode(qr_base64)
            attachments = [('flight_qr.png', qr_bytes, 'image/png')]
            email_sent = send_email(emails, subject, body, attachments)
            logger.info(f"Email send result: {email_sent}")

    logger.info(f"Flight link created: {share_url}")
    return jsonify({
        'success': True,
        'url': share_url,
        'qr': qr_base64
    })


@app.route('/admin/download_manifest')
def download_manifest():
    """Download the manifest CSV for a flight."""
    key = request.args.get('key', '')
    if key != ADMIN_KEY:
        return "Unauthorized", 401

    flight_id = request.args.get('flight_id', '')
    if not flight_id:
        return "Missing flight_id", 400

    manifest_path = MANIFEST_DIR / f"{flight_id}.csv"
    if not manifest_path.exists():
        return "Manifest not found", 404

    return send_file(
        manifest_path,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"{flight_id}_manifest.csv"
    )


@app.route('/admin/download_tickets')
def download_tickets():
    """Download all tickets for a flight as a ZIP."""
    key = request.args.get('key', '')
    if key != ADMIN_KEY:
        return "Unauthorized", 401

    flight_id = request.args.get('flight_id', '')
    if not flight_id:
        return "Missing flight_id", 400

    flight_dir = TICKETS_DIR / flight_id
    if not flight_dir.exists():
        return "No tickets found", 404

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for pdf_file in flight_dir.glob("*.pdf"):
            zf.writestr(pdf_file.name, pdf_file.read_bytes())

    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f"{flight_id}_tickets.zip"
    )


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == '__main__':
    # Write embedded logo for verification
    write_embedded_logo()

    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting BAC Helicopters Ticketing System on port {port}")
    logger.info(f"SMTP configured: {is_smtp_configured()}")
    logger.info(f"SharePoint configured: {bool(SP_DRIVE_ID)}")

    app.run(host='0.0.0.0', port=port, debug=False)
