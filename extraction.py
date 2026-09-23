# its a ticket-information interpreter. we can say how our ticket is. messy or clean or complete like that senarios
# here we are handling missing, inconsistent ticket data, through various regex expressions



import re
from typing import Any, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Store code must be exactly 6 alphanumeric characters.
STORE_CODE_PATTERN = re.compile(r"\b[A-Za-z0-9]{6}\b")


# Work-type keywords from the assignment.
MAINTENANCE_PATTERN = re.compile(
    r"\b(?:PM|AMC|maintenance|maintain|preventive maintenance)\b",
    re.IGNORECASE,
)

INSTALLATION_PATTERN = re.compile(
    r"\b(?:installation|install|new installation)\b",
    re.IGNORECASE,
)

SERVICE_CALL_PATTERN = re.compile(
    r"\b(?:fault|not working|complaint|service call|breakdown)\b",
    re.IGNORECASE,
)


# Common indicators for automated/noise tickets.
#
# This is intentionally conservative. We should not exclude a ticket
# merely because it contains one generic word.
NOISE_PATTERNS = [
    re.compile(
        r"\b(?:automated alert|automatic alert|system alert)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:marketing|promotional|promotion|newsletter|unsubscribe)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:spam|test ticket|test email)\b",
        re.IGNORECASE,
    ),
]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def normalize_text(value: Any) -> str:
    """Convert a value to a clean string."""
    if value is None:
        return ""

    return str(value).strip()


def normalize_email(value: Any) -> str:
    """Normalize an email address for matching."""
    return normalize_text(value).lower()


# ---------------------------------------------------------------------------
# Store-code extraction
# ---------------------------------------------------------------------------

def extract_store_code(*values: Any) -> Optional[str]:
    """
    Extract the first 6-character alphanumeric store code.

    The assignment says the store code may need to be extracted from
    the subject or requester email.

    Examples:
        "PM At OMNIMART M9GDCU 2ND MEKANZU DVR"
            -> "M9GDCU"

        "store-m9gdcu@example.com"
            -> "m9gdcu"
    """
    for value in values:
        text = normalize_text(value)

        if not text:
            continue

        match = STORE_CODE_PATTERN.search(text)

        if match:
            return match.group(0)

    return None


# ---------------------------------------------------------------------------
# Work-type extraction
# ---------------------------------------------------------------------------

def extract_work_type(*values: Any) -> str:
    """
    Determine work type from subject/requester information.

    Assignment rules:
        PM / AMC       -> Maintenance
        installation   -> Installation
        fault /
        not working /
        complaint     -> Service Call
        otherwise      -> Other
    """
    text = " ".join(
        normalize_text(value)
        for value in values
        if normalize_text(value)
    )

    if not text:
        return "Other"

    if MAINTENANCE_PATTERN.search(text):
        return "Maintenance"

    if INSTALLATION_PATTERN.search(text):
        return "Installation"

    if SERVICE_CALL_PATTERN.search(text):
        return "Service Call"

    return "Other"


# ---------------------------------------------------------------------------
# Noise-ticket detection
# ---------------------------------------------------------------------------

def detect_noise(
    subject: Any,
    requester_name: Any = "",
    requester_email: Any = "",
) -> Tuple[bool, Optional[str]]:
    """
    Detect obvious noise tickets.

    The assignment permits excluding automated alerts and marketing
    spam when the exclusion is documented.

    This function therefore returns both:
        (is_noise, reason)

    We keep this conservative so legitimate operational tickets are
    not accidentally removed.
    """
    text = " ".join(
        normalize_text(value)
        for value in (
            subject,
            requester_name,
            requester_email,
        )
        if normalize_text(value)
    )

    if not text:
        return False, None

    for pattern in NOISE_PATTERNS:
        match = pattern.search(text)

        if match:
            return True, match.group(0)

    # Explicit no-reply/system sender can be an automated source,
    # but don't automatically exclude it unless the subject also
    # looks like an alert.
    email = normalize_email(requester_email)

    if email:
        automated_sender = (
            "no-reply@" in email
            or "noreply@" in email
            or "donotreply@" in email
        )

        alert_subject = bool(
            re.search(
                r"\b(?:alert|notification|automated)\b",
                normalize_text(subject),
                re.IGNORECASE,
            )
        )

        if automated_sender and alert_subject:
            return True, "automated alert"

    return False, None


# ---------------------------------------------------------------------------
# Document-field validation
# ---------------------------------------------------------------------------

def is_url(value: Any) -> bool:
    """
    Check whether a document value is a URL.

    Document rules from the assignment:
        URL   -> valid document
        empty -> missing
        NA    -> waiver where permitted
        other -> junk
    """
    value = normalize_text(value)

    return value.startswith(("http://", "https://"))


def is_exact_na(value: Any) -> bool:
    """Only exact uppercase 'NA' counts as the waiver."""
    return normalize_text(value) == "NA"


def is_empty(value: Any) -> bool:
    """Return True for None or an empty/whitespace-only value."""
    return normalize_text(value) == ""


def classify_document(value: Any) -> str:
    """
    Classify a raw document field.

    Returns one of:
        url
        na
        empty
        junk
    """
    if is_url(value):
        return "url"

    if is_exact_na(value):
        return "na"

    if is_empty(value):
        return "empty"

    return "junk"


def document_counts_as_present(
    field_name: str,
    value: Any,
) -> bool:
    """
    Determine whether a document satisfies its workflow step.

    Rules:
        Purchase Order -> URL only
        Delivery Note  -> URL or NA
        Work Report    -> URL only
        Invoice        -> URL or NA

    Empty and junk values never satisfy the step.
    """
    document_type = classify_document(value)

    if field_name in {
        "purchase_order",
        "work_report",
    }:
        return document_type == "url"

    if field_name in {
        "delivery_note",
        "invoice",
    }:
        return document_type in {"url", "na"}

    return False


# ---------------------------------------------------------------------------
# Ticket extraction
# ---------------------------------------------------------------------------

def extract_ticket_metadata(
    ticket: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract the useful normalized metadata from one raw API ticket.

    This does not modify the original ticket.
    """
    subject = normalize_text(
        ticket.get("subject")
    )

    requester_name = normalize_text(
        ticket.get("requester_name")
    )

    requester_email = normalize_email(
        ticket.get("requester_email")
    )

    store_code = extract_store_code(
        subject,
        requester_email,
    )

    work_type = extract_work_type(
        subject,
        requester_email,
    )

    is_noise, noise_reason = detect_noise(
        subject=subject,
        requester_name=requester_name,
        requester_email=requester_email,
    )

    document_states = {
        field_name: classify_document(
            ticket.get(field_name)
        )
        for field_name in (
            "purchase_order",
            "delivery_note",
            "work_report",
            "invoice",
        )
    }

    return {
        "store_code": store_code or "",
        "work_type": work_type,
        "is_noise": is_noise,
        "noise_reason": noise_reason or "",
        "document_states": document_states,
    }


# ---------------------------------------------------------------------------
# Manager / Engineer validation helpers
# ---------------------------------------------------------------------------

def validate_manager_name(
    manager: Any,
    manager_names: set[str],
) -> bool:
    """
    Validate a ticket's plain-text manager name against the roster.

    Matching is case-insensitive, but the original ticket value is
    preserved elsewhere because the sheet contract says Manager is
    the string on the ticket.
    """
    manager_name = normalize_text(manager)

    if not manager_name:
        return False

    normalized_roster = {
        normalize_text(name).casefold()
        for name in manager_names
        if normalize_text(name)
    }

    return manager_name.casefold() in normalized_roster


def validate_engineer_id(
    engineer_id: Any,
    engineer_ids: set[int],
) -> bool:
    """Validate that engineer_id exists in the Engineer roster."""
    if engineer_id in (None, ""):
        return False

    try:
        numeric_id = int(engineer_id)
    except (TypeError, ValueError):
        return False

    return numeric_id in engineer_ids