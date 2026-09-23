#  used for missing things, assigning things, also like PO missing then it goes to manager not engineer or finance employ kind of thing, if Work Report is missing then it goes to engineer, if Delivery Note is missing then it goes to finance, if invoice is missing then it goes to finance, if manager is missing then it goes to coordinator, if engineer is missing then it goes to manager, if everything is complete then stage is done and action owner is blank. Integrity field is used for checking if the ticket has any issues like invalid engineer_id or invalid manager.
# Priority things we are doing here is to check the workflow of the ticket and determine the stage, action owner, and integrity of the ticket based on the rules defined in the workflow. The workflow consists of six steps: Assign Manager, Assign Engineer, Purchase Order, Delivery Note, Work Report, and Invoice. Each step has specific requirements that must be met for the ticket to progress to the next stage. The code also includes helper functions for normalizing values, checking if values are blank or valid URLs, and building lookups for agents and managers.

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Workflow constants
# ---------------------------------------------------------------------------

STAGE_ASSIGN_MANAGER = "Assign Manager"
STAGE_ASSIGN_ENGINEER = "Assign Engineer"
STAGE_PURCHASE_ORDER = "Purchase Order"
STAGE_DELIVERY_NOTE = "Delivery Note"
STAGE_WORK_REPORT = "Work Report"
STAGE_INVOICE = "Invoice"
STAGE_DONE = "Done"

ROLE_COORDINATOR = "Coordinator"
ROLE_MANAGER = "Manager"
ROLE_ENGINEER = "Engineer"
ROLE_FINANCE = "Finance"


# ---------------------------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------------------------

def normalize_value(value: Any) -> str:
    """
    Convert a value to a clean string.

    None becomes an empty string.
    """
    if value is None:
        return ""

    return str(value).strip()


def is_blank(value: Any) -> bool:
    """Return True when the value is empty or missing."""
    return normalize_value(value) == ""


def is_na(value: Any) -> bool:
    """Return True when the document field is exactly NA."""
    return normalize_value(value).upper() == "NA"


def is_url(value: Any) -> bool:
    """
    Return True when the value is an HTTP/HTTPS URL.
    """
    value = normalize_value(value)

    return value.startswith("http://") or value.startswith("https://")


def document_is_valid(
    value: Any,
    *,
    allow_na: bool = False,
) -> bool:
    """
    Check whether a workflow document field satisfies the assignment rules.

    Valid values are:
      - HTTP/HTTPS URL
      - exact NA when the document is waivable

    Blank values and arbitrary text are not valid.
    """
    if is_url(value):
        return True

    if allow_na and is_na(value):
        return True

    return False


# ---------------------------------------------------------------------------
# Agent / roster helpers
# ---------------------------------------------------------------------------

def build_agent_lookup(
    agents: List[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    """
    Build an agent lookup keyed by numeric agent ID.
    """
    lookup: Dict[int, Dict[str, Any]] = {}

    for agent in agents:
        agent_id = agent.get("id")

        try:
            agent_id_int = int(agent_id)
        except (TypeError, ValueError):
            continue

        lookup[agent_id_int] = agent

    return lookup


def build_manager_lookup(
    agents: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Build a manager lookup keyed by normalized manager name.
    """
    lookup: Dict[str, Dict[str, Any]] = {}

    for agent in agents:
        role = normalize_value(agent.get("role"))

        if role != ROLE_MANAGER:
            continue

        name = normalize_value(agent.get("name"))

        if not name:
            continue

        lookup[name.casefold()] = agent

    return lookup


def get_engineer_name(
    engineer_id: Any,
    agent_lookup: Dict[int, Dict[str, Any]],
) -> str:
    """
    Convert engineer_id into the exact roster name.

    Returns an empty string when the engineer ID is missing
    or not found in the roster.
    """
    if engineer_id in (None, ""):
        return ""

    try:
        engineer_id_int = int(engineer_id)
    except (TypeError, ValueError):
        return ""

    agent = agent_lookup.get(engineer_id_int)

    if not agent:
        return ""

    return normalize_value(agent.get("name"))


def manager_is_valid(
    manager_name: Any,
    manager_lookup: Dict[str, Dict[str, Any]],
) -> bool:
    """
    Validate a ticket manager name against the manager roster.
    """
    manager_name = normalize_value(manager_name)

    if not manager_name:
        return False

    return manager_name.casefold() in manager_lookup


# ---------------------------------------------------------------------------
# Coordinator ownership
# ---------------------------------------------------------------------------

def get_coordinator_name(
    ticket_id: Any,
    agents: List[Dict[str, Any]],
) -> str:
    """
    Determine coordinator ownership using the assignment rule:

        coordinators_sorted_by_name[ticket_id % 2]

    Coordinators are sorted alphabetically by name.
    """
    coordinators = [
        agent
        for agent in agents
        if normalize_value(agent.get("role")) == ROLE_COORDINATOR
    ]

    coordinators.sort(
        key=lambda agent: normalize_value(agent.get("name")).casefold()
    )

    if not coordinators:
        return ""

    try:
        ticket_id_int = int(ticket_id)
    except (TypeError, ValueError):
        return ""

    index = ticket_id_int % 2

    if index >= len(coordinators):
        return ""

    return normalize_value(coordinators[index].get("name"))


# ---------------------------------------------------------------------------
# Role ownership helpers
# ---------------------------------------------------------------------------

def get_manager_owner(
    manager_name: Any,
) -> str:
    """
    The manager owns engineer assignment, PO and related manager steps.
    """
    return normalize_value(manager_name)


def get_engineer_owner(
    engineer_id: Any,
    agent_lookup: Dict[int, Dict[str, Any]],
) -> str:
    """
    The assigned engineer owns the work report.
    """
    return get_engineer_name(
        engineer_id,
        agent_lookup,
    )


def get_finance_owner(
    agents: List[Dict[str, Any]],
) -> str:
    """
    Return the Finance agent name.

    The assignment defines Finance as the owner of:
      - Delivery Note
      - Invoice
    """
    finance_agents = [
        agent
        for agent in agents
        if normalize_value(agent.get("role")) == ROLE_FINANCE
    ]

    finance_agents.sort(
        key=lambda agent: normalize_value(agent.get("name")).casefold()
    )

    if not finance_agents:
        return ""

    return normalize_value(finance_agents[0].get("name"))


# ---------------------------------------------------------------------------
# Workflow evaluation
# ---------------------------------------------------------------------------

def evaluate_workflow(
    ticket: Dict[str, Any],
    agents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Evaluate the ticket according to the six-step FieldServe workflow.

    Workflow:

    1. Assign Manager
    2. Assign Engineer
    3. Purchase Order
    4. Delivery Note
    5. Work Report
    6. Invoice

    The first unmet step becomes the Stage.
    The responsible person becomes Action Owner.
    """

    ticket_id = ticket.get("id")

    manager = normalize_value(ticket.get("manager"))
    engineer_id = ticket.get("engineer_id")

    purchase_order = ticket.get("purchase_order")
    delivery_note = ticket.get("delivery_note")
    work_report = ticket.get("work_report")
    invoice = ticket.get("invoice")

    agent_lookup = build_agent_lookup(agents)

    finance_owner = get_finance_owner(agents)

    coordinator_owner = get_coordinator_name(
        ticket_id,
        agents,
    )

    # ------------------------------------------------------------------
    # Step 1: Assign Manager
    # ------------------------------------------------------------------

    if not manager:
        return {
            "stage": STAGE_ASSIGN_MANAGER,
            "action_owner": coordinator_owner,
            "integrity": "",
        }

    # ------------------------------------------------------------------
    # Step 2: Assign Engineer
    # ------------------------------------------------------------------

    if engineer_id in (None, ""):
        return {
            "stage": STAGE_ASSIGN_ENGINEER,
            "action_owner": get_manager_owner(manager),
            "integrity": "",
        }

    # ------------------------------------------------------------------
    # Step 3: Purchase Order
    # ------------------------------------------------------------------

    if not is_url(purchase_order):
        return {
            "stage": STAGE_PURCHASE_ORDER,
            "action_owner": get_manager_owner(manager),
            "integrity": "",
        }

    # ------------------------------------------------------------------
    # Step 4: Delivery Note
    #
    # Delivery Note is waivable, therefore:
    #   URL = complete
    #   NA  = complete
    # ------------------------------------------------------------------

    if not document_is_valid(
        delivery_note,
        allow_na=True,
    ):
        return {
            "stage": STAGE_DELIVERY_NOTE,
            "action_owner": finance_owner,
            "integrity": "",
        }

    # ------------------------------------------------------------------
    # Step 5: Work Report
    #
    # Work Report is never waivable.
    # Only URL counts.
    # ------------------------------------------------------------------

    if not is_url(work_report):
        return {
            "stage": STAGE_WORK_REPORT,
            "action_owner": get_engineer_owner(
                engineer_id,
                agent_lookup,
            ),
            "integrity": "",
        }

    # ------------------------------------------------------------------
    # Step 6: Invoice
    #
    # Invoice is waivable:
    #   URL = complete
    #   NA  = complete
    # ------------------------------------------------------------------

    if not document_is_valid(
        invoice,
        allow_na=True,
    ):
        return {
            "stage": STAGE_INVOICE,
            "action_owner": finance_owner,
            "integrity": "",
        }

    # ------------------------------------------------------------------
    # All workflow steps complete
    # ------------------------------------------------------------------

    integrity_issues = []

    # Engineer ID should exist in the roster.
    try:
        engineer_id_int = int(engineer_id)
    except (TypeError, ValueError):
        engineer_id_int = None

    if engineer_id_int is None or engineer_id_int not in agent_lookup:
        integrity_issues.append("Invalid engineer_id")

    # Manager should match the manager roster.
    manager_lookup = build_manager_lookup(agents)

    if not manager_is_valid(
        manager,
        manager_lookup,
    ):
        integrity_issues.append("Invalid manager")

    # Closed tickets should have all six workflow steps complete.
    status = ticket.get("status")

    if status == 5 and integrity_issues:
        integrity = "; ".join(integrity_issues)
    else:
        integrity = "; ".join(integrity_issues)

    return {
        "stage": STAGE_DONE,
        "action_owner": "",
        "integrity": integrity,
    }


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

def status_label(status: Any) -> str:
    """
    Convert the FieldServe numeric status to the required sheet label.

    2 = Open
    3 = Pending
    4 = Resolved
    5 = Closed
    """
    try:
        status_int = int(status)
    except (TypeError, ValueError):
        return ""

    mapping = {
        2: "Open",
        3: "Pending",
        4: "Resolved",
        5: "Closed",
    }

    return mapping.get(status_int, "")


# ---------------------------------------------------------------------------
# Computed fields
# ---------------------------------------------------------------------------

def build_computed_fields(
    ticket: Dict[str, Any],
    agents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build all computed workflow fields used by the spreadsheet.
    """
    result = evaluate_workflow(
        ticket,
        agents,
    )

    return {
        "Stage": result.get("stage", ""),
        "Action Owner": result.get("action_owner", ""),
        "Integrity": result.get("integrity", ""),
    }