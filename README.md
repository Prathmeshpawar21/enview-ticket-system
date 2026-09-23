# FieldServe Ticket Board

Two-way synchronization between the FieldServe helpdesk API and a real Excel spreadsheet.

**GitHub Repository:**  
**Repository:** [github.com/Prathmeshpawar21/enview-ticket-system](https://github.com/Prathmeshpawar21/enview-ticket-system)


The spreadsheet answers:

- What is this ticket waiting on?
- Whose move is it?

## Project Structure

```text
├── api.py              # FieldServe API client
├── extraction.py       # Store/work-type extraction and data validation
├── workflow.py         # Stage, Action Owner and workflow rules
├── storage.py          # Excel and sync-state persistence
├── sheet.py            # Grader CLI: export/apply
├── sync.py             # Main two-way synchronization
├── fieldserve.xlsx     # Operational spreadsheet
├── sync_state.json     # Previous sync state
├── submission.json     # Grader command configuration
├── requirements.txt    # Python dependencies
└── README.md
```

## Setup

Python 3 is required.

```bash
pip install -r requirements.txt
```

Set the required environment variables:

```env
FIELDOPS_BASE_URL=http://13.233.55.184:8377
FIELDOPS_API_KEY=<our-api-key>
```

The API key is used as the Basic Auth username.
 

## Synchronization

Run one complete synchronization cycle:

```bash
python3 sync.py
```

The sync:

1. Fetches agents and tickets from FieldServe.
2. Reads the current Excel state.
3. Compares both sides with the previous sync state.
4. Pushes spreadsheet-only changes to the API.
5. Applies server-only changes to Excel.
6. Resolves simultaneous changes using the documented conflict policy.
7. Recalculates Stage and Action Owner.
8. Saves the spreadsheet and synchronization state.

### Conflict Policy

The FieldServe API is treated as the authoritative server state.

- **Only Excel changed:** push the Excel change to the API.
- **Only API changed:** update Excel from the API.
- **Both changed the same field:** server wins.

This prevents a stale spreadsheet value from overwriting a newer server-side change.

## Spreadsheet

The real spreadsheet is:

```text
fieldserve.xlsx
```

Required columns:

```text
Ticket ID
Subject
Status
Engineer
Manager
Purchase Order
Delivery Note
Work Report
Invoice
Stage
Action Owner
```

## Workflow

Workflow is evaluated in this exact order:

```text
1. Assign Manager
2. Assign Engineer
3. Purchase Order
4. Delivery Note
5. Work Report
6. Invoice
```

The **first unmet step** becomes `Stage`.

The responsible person becomes `Action Owner`.

If every step is complete:

```text
Stage = Done
Action Owner = blank
```

### Assign Manager

The Manager step is complete when `manager` is non-empty.

The coordinator owns this step. Coordinator ownership follows the ticket-ID parity rule from the assignment.

### Assign Engineer

The Engineer step is complete when `engineer_id` is set.

The manager owns this step.

### Purchase Order

Purchase Order is complete only when it contains a valid URL.

`NA` does not waive Purchase Order.

The manager owns this step.

### Delivery Note

Delivery Note is complete when it contains either:

- a valid URL, or
- exact `NA`

Finance owns this step.

### Work Report

Work Report is complete only when it contains a valid URL.

It cannot be waived with `NA`.

The assigned engineer owns this step.

### Invoice

Invoice is complete when it contains either:

- a valid URL, or
- exact `NA`

Finance owns this step.

## Document Validation

Document fields accept:

- a valid URL
- empty
- exact `NA` where the workflow allows it

Other non-empty text is treated as invalid/junk and does not satisfy the workflow requirement.

## Status Mapping

| API value | Spreadsheet value |
|---:|---|
| `2` | Open |
| `3` | Pending |
| `4` | Resolved |
| `5` | Closed |

## Integrity

The workflow logic checks for problematic data such as:

- Invalid manager names
- Invalid engineer IDs
- Engineer IDs referencing non-engineer agents
- Invalid document values
- Closed tickets missing required workflow steps
- Resolved tickets missing a Work Report

## API Pagination

The API limits ticket pagination to 10 pages with a maximum of 50 tickets per page.

The implementation uses `updated_since` to continue through larger datasets and deduplicates tickets by Ticket ID.

Tickets are processed according to the API's documented `updated_at` ordering.

## API Rate Limiting

The API has a documented rate limit of 60 requests/minute.

For `429 Too Many Requests`, the client uses `Retry-After` with bounded retries.

## Messy Data

The implementation handles:

- Store-code extraction from subject/requester email
- Work-type classification
- Invalid document values
- Manager validation against the roster
- Engineer ID resolution through the agent roster
- Conservative noise-ticket filtering

## Sheet CLI

The grader interacts with the spreadsheet through `sheet.py`.

### Export

```bash
python3 sheet.py export /tmp/out.csv
```

Exports the current spreadsheet values using the required 11-column contract.

Computed values such as `Stage` and `Action Owner` are exported as displayed values.

### Apply

```bash
python3 sheet.py apply /tmp/edits.csv
```

Input format:

```csv
Ticket ID,Column,Value
122508,Manager,Pahifan Kinga
```

Editable columns are:

```text
Status
Engineer
Manager
Purchase Order
Delivery Note
Work Report
Invoice
```

`sheet.py apply` changes only the local Excel workbook.

It does **not** call the API or run synchronization.

The next:

```bash
python3 sync.py
```

will synchronize the change.

## New Tickets

New tickets returned by the API are added to the spreadsheet.

Their ticket fields, Stage, and Action Owner are calculated from the server ticket.

## Engineer and Manager Handling

`engineer_id` is treated as a foreign key into the agent roster.

The Engineer value displayed in Excel is resolved from the agent name.

The Manager field is stored by the API as a name string and is validated against the manager roster before spreadsheet edits are pushed to the API.

## Testing

The implementation was tested for:

- Full synchronization
- No-change synchronization
- Excel → API changes
- API → Excel changes
- Same-field conflicts
- API pagination beyond 500 tickets
- Workflow Stage and Action Owner
- `NA` handling
- Invalid document values
- CSV export
- CSV apply without an API side effect

## Submission

`submission.json` contains:

```json
{
  "sync_cmd": "python3 sync.py",
  "sheet_cmd": "python3 sheet.py"
}
```

Both commands are intended to run from the repository root.

## Assumptions

1. The FieldServe API is the authoritative server state.
2. Excel is the operational working view.
3. `sync_state.json` stores the previous synchronized state.
4. When both sides change the same field, the server value wins.
5. Computed workflow fields are derived from the current ticket state.
6. Computed fields are not manually editable through the grader's apply interface.
7. Document fields only count when they contain a valid URL or an allowed `NA` waiver.
8. Noise detection is conservative.
