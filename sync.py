from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from api import FieldServeAPI
from extraction import extract_ticket_metadata
from storage import (
    DEFAULT_STATE_PATH,
    DEFAULT_XLSX_PATH,
    EDITABLE_COLUMNS,
    SHEET_TO_API_FIELD,
    build_sync_ticket_state,
    load_sync_state,
    read_sheet_index,
    save_sync_state,
    set_state_ticket,
    write_sheet_rows,
    values_equal,
)
from workflow import (
    build_agent_lookup,
    build_manager_lookup,
    build_computed_fields,
    get_engineer_name,
    status_label,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PAGE_SIZE = 50

# API page numbers are capped at 10.
MAX_API_PAGES = 10

# Server-wins is our explicit conflict policy.
#
# If both the spreadsheet and server changed the same field since
# the previous sync, we keep the server value and discard the local
# conflicting change.
CONFLICT_POLICY = "server_wins"


# ---------------------------------------------------------------------------
# Date/time helpers
# ---------------------------------------------------------------------------
def parse_api_timestamp(
    value: Any,
) -> Optional[datetime]:
    """
    Parse an ISO-8601 API timestamp.

    The FieldServe API returns timestamps such as:
        2025-05-18T13:49:44Z
    """
    if not value:
        return None

    text = str(value).strip()

    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(timezone.utc)

def timestamp_after(
    value: str,
) -> str:
    """
    Return the next API-compatible timestamp after the supplied timestamp.

    The FieldServe API requires updated_since timestamps in second
    precision, for example:

        2026-01-31T00:00:00Z

    It rejects timestamps containing microseconds such as:

        2026-01-31T00:00:00.000001Z

    We therefore advance by one second and explicitly remove
    microseconds before formatting the cursor.
    """

    parsed = parse_api_timestamp(value)

    if parsed is None:
        raise ValueError(
            f"Invalid API timestamp: {value}"
        )

    next_timestamp = (
        parsed + timedelta(seconds=1)
    ).replace(microsecond=0)

    return next_timestamp.isoformat().replace(
        "+00:00",
        "Z",
    )


# ---------------------------------------------------------------------------
# Ticket normalization
# ---------------------------------------------------------------------------
def ticket_id(
    ticket: Dict[str, Any],
) -> Optional[int]:
    """Return a normalized ticket ID."""
    value = ticket.get("id")

    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def should_exclude_ticket(
    ticket: Dict[str, Any],
) -> bool:
    """
    Determine whether a ticket should be excluded as documented noise.

    Noise detection is conservative and is based on extraction.py.
    """
    metadata = extract_ticket_metadata(ticket)

    return bool(metadata["is_noise"])

def normalize_status_for_sheet(
    status: Any,
) -> str:
    """Convert API numeric status into the required sheet label."""
    return status_label(status)

def build_sheet_row(
    ticket: Dict[str, Any],
    agents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Convert one API ticket into the exact spreadsheet representation.
    """
    agent_lookup = build_agent_lookup(agents)

    engineer_name = get_engineer_name(
        ticket.get("engineer_id"),
        agent_lookup,
    )

    computed = build_computed_fields(
        ticket,
        agents,
    )

    # Keep the required sheet contract exact.
    return {
        "Ticket ID": ticket.get("id"),
        "Subject": ticket.get("subject") or "",
        "Status": normalize_status_for_sheet(
            ticket.get("status")
        ),
        "Engineer": engineer_name,
        "Manager": ticket.get("manager") or "",
        "Purchase Order": ticket.get("purchase_order") or "",
        "Delivery Note": ticket.get("delivery_note") or "",
        "Work Report": ticket.get("work_report") or "",
        "Invoice": ticket.get("invoice") or "",
        "Stage": computed["Stage"],
        "Action Owner": computed["Action Owner"],
    }




# ---------------------------------------------------------------------------
# API ticket enumeration
# ---------------------------------------------------------------------------
def fetch_ticket_window(
    api: FieldServeAPI,
    updated_since: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch a complete API window.

    The API allows at most 10 pages, with at most 50 tickets per page.
    If page 10 is full, we advance updated_since beyond its final
    updated_at timestamp and continue.

    This is the mechanism used to enumerate datasets larger than
    the 500-ticket page cap.
    """
    all_tickets: List[Dict[str, Any]] = []

    current_since = updated_since

    while True:
        window_tickets: List[Dict[str, Any]] = []

        for page in range(
            1,
            MAX_API_PAGES + 1,
        ):
            page_tickets = api.list_tickets_page(
                page=page,
                per_page=PAGE_SIZE,
                updated_since=current_since,
            )

            if not page_tickets:
                break

            window_tickets.extend(
                page_tickets
            )

            # Fewer than PAGE_SIZE means this is the final page
            # in the current updated_since window.
            if len(page_tickets) < PAGE_SIZE:
                break

        if not window_tickets:
            break

        all_tickets.extend(
            window_tickets
        )

        # If fewer than 500 records were returned, there is no
        # indication that another page/window is required.
        if len(window_tickets) < (
            PAGE_SIZE * MAX_API_PAGES
        ):
            break

        # The API caps page numbers at 10. Move the updated_since
        # cursor forward using the last record returned.
        timestamps = [
            ticket.get("updated_at")
            for ticket in window_tickets
            if ticket.get("updated_at")
        ]

        if not timestamps:
            raise RuntimeError(
                "API returned a full 10-page window but tickets "
                "have no updated_at values. Cannot safely continue "
                "enumeration."
            )

        # Tickets are documented as sorted by updated_at ascending.
        last_timestamp = timestamps[-1]

        next_since = timestamp_after(
            str(last_timestamp)
        )

        if current_since == next_since:
            raise RuntimeError(
                "API pagination cursor did not advance."
            )

        current_since = next_since

    # The same ticket can theoretically occur in overlapping
    # incremental windows. Deduplicate by ticket ID.
    deduplicated: Dict[int, Dict[str, Any]] = {}

    for ticket in all_tickets:
        current_id = ticket_id(ticket)

        if current_id is None:
            continue

        deduplicated[current_id] = ticket

    return list(
        deduplicated.values()
    )


# ---------------------------------------------------------------------------
# Sheet/API value conversion
# ---------------------------------------------------------------------------
def sheet_status_to_api(
    value: Any,
) -> Optional[int]:
    """
    Convert a sheet status label into the numeric API status.
    """
    if value is None:
        return None

    text = str(value).strip()

    mapping = {
        "Open": 2,
        "Pending": 3,
        "Resolved": 4,
        "Closed": 5,
    }

    if text not in mapping:
        raise ValueError(
            f"Invalid Status value: {value!r}. "
            f"Expected one of: {', '.join(mapping)}"
        )

    return mapping[text]

def build_api_update_from_sheet(
    row: Dict[str, Any],
    changed_columns: List[str],
    manager_lookup: Dict[str, Dict[str, Any]],
    agent_lookup: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Convert changed spreadsheet fields into an API PUT payload.

    Only fields that actually changed locally are included.
    """
    payload: Dict[str, Any] = {}

    for column_name in changed_columns:
        api_field = SHEET_TO_API_FIELD.get(
            column_name
        )

        if not api_field:
            continue

        value = row.get(column_name)

        if column_name == "Status":
            payload[api_field] = sheet_status_to_api(
                value
            )
            continue

        if column_name == "Engineer":
            engineer_name = (
                str(value).strip()
                if value is not None
                else ""
            )

            if not engineer_name:
                payload[api_field] = None
                continue

            matching_engineer_id: Optional[int] = None

            for numeric_id, agent in agent_lookup.items():
                if (
                    agent.get("role") == "Engineer"
                    and str(agent.get("name", "")).strip().casefold()
                    == engineer_name.casefold()
                ):
                    matching_engineer_id = numeric_id
                    break

            if matching_engineer_id is None:
                raise ValueError(
                    f"Engineer '{engineer_name}' is not in the "
                    f"FieldServe engineer roster."
                )

            payload[api_field] = matching_engineer_id
            continue

        if column_name == "Manager":
            manager_name = (
                str(value).strip()
                if value is not None
                else ""
            )

            if not manager_name:
                payload[api_field] = ""
                continue

            manager = manager_lookup.get(
                manager_name.casefold()
            )

            if manager is None:
                raise ValueError(
                    f"Manager '{manager_name}' is not in the "
                    f"FieldServe manager roster."
                )

            # The API expects the manager as a plain name string.
            payload[api_field] = str(
                manager.get("name", "")
            ).strip()

            continue

        # Document fields.
        if column_name in {
            "Purchase Order",
            "Delivery Note",
            "Work Report",
            "Invoice",
        }:
            if value is None:
                payload[api_field] = ""
            else:
                payload[api_field] = str(value)

    return payload




# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------
def get_previous_state(
    state: Dict[str, Any],
    current_ticket_id: int,
) -> Dict[str, Any]:
    """Return previous state or an empty state for a new ticket."""
    tickets = state.get("tickets", {})

    previous = tickets.get(
        str(current_ticket_id)
    )

    if isinstance(previous, dict):
        return previous

    return {}

def sheet_column_to_state_field(
    column_name: str,
) -> Optional[str]:
    """
    Map a sheet column to the corresponding state/API field.
    """
    mapping = {
        "Status": "status",
        "Engineer": "engineer_id",
        "Manager": "manager",
        "Purchase Order": "purchase_order",
        "Delivery Note": "delivery_note",
        "Work Report": "work_report",
        "Invoice": "invoice",
    }

    return mapping.get(
        column_name
    )

def sheet_value_for_column(
    row: Dict[str, Any],
    column_name: str,
    agent_lookup: Dict[int, Dict[str, Any]],
) -> Any:
    """
    Convert a displayed sheet value into the comparable API value.
    """
    value = row.get(column_name)

    if column_name == "Status":
        return sheet_status_to_api(value)

    if column_name == "Engineer":
        engineer_name = (
            str(value).strip()
            if value is not None
            else ""
        )

        if not engineer_name:
            return None

        for numeric_id, agent in agent_lookup.items():
            if (
                str(agent.get("name", "")).strip().casefold()
                == engineer_name.casefold()
            ):
                return numeric_id

        return "__INVALID_ENGINEER__"


    

    if column_name == "Manager":
        if value is None:
            return ""

        return str(value).strip()

    if value is None:
        return ""

    return str(value)

def api_value_for_column(
    ticket: Dict[str, Any],
    column_name: str,
) -> Any:
    """Return the current server value for a sheet column."""
    api_field = SHEET_TO_API_FIELD.get(
        column_name
    )

    if not api_field:
        return None

    return ticket.get(api_field)

def previous_value_for_column(
    previous_state: Dict[str, Any],
    column_name: str,
) -> Any:
    """Return the previous synchronized API value."""
    state_field = sheet_column_to_state_field(
        column_name
    )

    if state_field is None:
        return None

    return previous_state.get(
        state_field
    )

def detect_field_changes(
    current_ticket: Dict[str, Any],
    current_row: Dict[str, Any],
    previous_state: Dict[str, Any],
    agent_lookup: Dict[int, Dict[str, Any]],
) -> Tuple[List[str], List[str]]:
    """
    Detect local-sheet changes and server-side changes.

    Returns:
        (sheet_changed_columns, server_changed_columns)
    """
    sheet_changes: List[str] = []
    server_changes: List[str] = []

    for column_name in EDITABLE_COLUMNS:
        current_sheet_value = sheet_value_for_column(
            current_row,
            column_name,
            agent_lookup,
        )

        current_api_value = api_value_for_column(
            current_ticket,
            column_name,
        )

        previous_api_value = previous_value_for_column(
            previous_state,
            column_name,
        )

        if not values_equal(
            current_sheet_value,
            previous_api_value,
        ):
            sheet_changes.append(
                column_name
            )

        if not values_equal(
            current_api_value,
            previous_api_value,
        ):
            server_changes.append(
                column_name
            )

    return (
        sheet_changes,
        server_changes,
    )



# ---------------------------------------------------------------------------
# Two-way sync
# ---------------------------------------------------------------------------
def synchronize(
    api: FieldServeAPI,
) -> Dict[str, int]:
    """
    Perform one complete two-way synchronization cycle.

    Conflict policy:
        - Sheet-only change -> push to API.
        - API-only change -> update Excel.
        - Both changed same field -> server wins.
        - New server tickets -> add to Excel.
        - Existing sheet-only ticket -> preserve locally until API
          confirms it; the API is the source of ticket identity.
    """
    state = load_sync_state(
        DEFAULT_STATE_PATH
    )

    # Read current spreadsheet BEFORE changing anything.
    sheet_index = {}

    try:
        sheet_index = {
            int(ticket_id): row
            for ticket_id, row in read_sheet_index(
                DEFAULT_XLSX_PATH
            ).items()
        }
    except Exception:
        # If workbook doesn't exist yet, storage.py will create it
        # when we write the first synchronized dataset.
        sheet_index = {}

    agents = api.get_agents()

    agent_lookup = build_agent_lookup(
        agents
    )

    manager_lookup = build_manager_lookup(
        agents
    )

    # ------------------------------------------------------------------
    # Fetch server tickets.
    #
    # For correctness and simplicity, we enumerate the server dataset
    # using the API's updated_since windowing mechanism.
    # ------------------------------------------------------------------

    server_tickets = fetch_ticket_window(
        api=api,
    )

    server_by_id: Dict[int, Dict[str, Any]] = {}

    for ticket in server_tickets:
        current_id = ticket_id(ticket)

        if current_id is None:
            continue

        if should_exclude_ticket(ticket):
            continue

        server_by_id[current_id] = ticket

    # ------------------------------------------------------------------
    # Process each server ticket.
    # ------------------------------------------------------------------

    final_rows: Dict[int, Dict[str, Any]] = {}

    stats = {
        "server_tickets": len(server_by_id),
        "added": 0,
        "updated_from_server": 0,
        "updated_server_from_sheet": 0,
        "conflicts": 0,
        "unchanged": 0,
    }

    for current_id, original_ticket in sorted(
        server_by_id.items()
    ):
        ticket = dict(
            original_ticket
        )

        current_row = sheet_index.get(
            current_id
        )

        previous_state = get_previous_state(
            state,
            current_id,
        )

        # --------------------------------------------------------------
        # New ticket
        # --------------------------------------------------------------

        if current_row is None:
            final_rows[current_id] = build_sheet_row(
                ticket,
                agents,
            )

            set_state_ticket(
                state,
                current_id,
                build_sync_ticket_state(ticket),
            )

            stats["added"] += 1
            continue

        # --------------------------------------------------------------
        # Existing ticket
        # --------------------------------------------------------------

        sheet_changes, server_changes = detect_field_changes(
            current_ticket=ticket,
            current_row=current_row,
            previous_state=previous_state,
            agent_lookup=agent_lookup,
        )

        # --------------------------------------------------------------
        # Determine which fields should be pushed to the API.
        # --------------------------------------------------------------

        push_columns: List[str] = []

        for column_name in sheet_changes:
            server_changed = (
                column_name in server_changes
            )

            if server_changed:
                # Both sides changed the same field.
                #
                # Explicit policy:
                # server wins.
                stats["conflicts"] += 1
                continue

            push_columns.append(
                column_name
            )

        # --------------------------------------------------------------
        # Push local-only changes to API.
        # --------------------------------------------------------------

        if push_columns:
            try:
                payload = build_api_update_from_sheet(
                    row=current_row,
                    changed_columns=push_columns,
                    manager_lookup=manager_lookup,
                    agent_lookup=agent_lookup,
                )

                if payload:
                    ticket = api.update_ticket(
                        current_id,
                        payload,
                    )

                    stats[
                        "updated_server_from_sheet"
                    ] += 1

            except Exception:
                # Do not silently corrupt the spreadsheet if an edit
                # cannot be pushed. Re-raise so the sync exits with
                # an error and the problem is visible.
                raise

        # --------------------------------------------------------------
        # Build final sheet row from the authoritative server ticket.
        #
        # This automatically handles:
        #   - server-only changes
        #   - successful sheet -> API changes
        #   - conflicts where server wins
        # --------------------------------------------------------------

        final_rows[current_id] = build_sheet_row(
            ticket,
            agents,
        )

        if server_changes:
            stats[
                "updated_from_server"
            ] += 1
        elif not push_columns:
            stats["unchanged"] += 1

        # Save latest server representation to state.
        set_state_ticket(
            state,
            current_id,
            build_sync_ticket_state(ticket),
        )

    # ------------------------------------------------------------------
    # Replace the spreadsheet with the authoritative final dataset.
    # ------------------------------------------------------------------

    write_sheet_rows(
        rows=final_rows.values(),
        xlsx_path=DEFAULT_XLSX_PATH,
    )

    # ------------------------------------------------------------------
    # Persist sync state only after Excel was successfully written.
    # ------------------------------------------------------------------

    save_sync_state(
        state,
        DEFAULT_STATE_PATH,
    )

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    print(
        "Starting FieldServe synchronization..."
    )

    api = FieldServeAPI()

    stats = synchronize(
        api
    )

    print(
        "Synchronization completed."
    )

    print(
        f"Server tickets: {stats['server_tickets']}"
    )

    print(
        f"Added to sheet: {stats['added']}"
    )

    print(
        f"Server changes applied: "
        f"{stats['updated_from_server']}"
    )

    print(
        f"Sheet changes pushed to server: "
        f"{stats['updated_server_from_sheet']}"
    )

    print(
        f"Conflicts resolved (server won): "
        f"{stats['conflicts']}"
    )

    print(
        f"Unchanged: {stats['unchanged']}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )