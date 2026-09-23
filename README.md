Next file: **`README.md`**.

This will document exactly how our implementation works, including setup, sync behavior, conflict policy, API limits, messy data handling, assumptions, and future work—the items the assignment explicitly asks the README to cover. 

Create:

```text
Enview-Assignment-Prathamesh/README.md
```

Put this:

````markdown
# FieldServe Ticket Board

A two-way synchronization tool between the FieldServe helpdesk API and a real Excel spreadsheet.

The goal is to provide an operational spreadsheet view that answers:

- What is this ticket waiting on?
- Whose move is it?

The spreadsheet is maintained in `fieldserve.xlsx`, while `sync.py` keeps it synchronized with the FieldServe API.

---

## Project Structure

```text
Enview-Assignment-Prathamesh/
├── .env
├── api.py
├── extraction.py
├── fieldserve.xlsx
├── README.md
├── requirements.txt
├── sheet.py
├── storage.py
├── submission.json
├── sync_state.json
├── sync.py
└── workflow.py
````

### File responsibilities

| File               | Responsibility                                                                           |
| ------------------ | ---------------------------------------------------------------------------------------- |
| `api.py`           | FieldServe HTTP API client, authentication, pagination, PUT updates, rate-limit handling |
| `extraction.py`    | Store-code extraction, work-type classification, noise detection, document validation    |
| `workflow.py`      | Stage, Action Owner, workflow rules, manager/engineer validation, integrity checks       |
| `storage.py`       | Excel workbook and synchronization-state persistence                                     |
| `sheet.py`         | Required grader CLI for spreadsheet export and local edits                               |
| `sync.py`          | Main two-way synchronization engine                                                      |
| `fieldserve.xlsx`  | Real spreadsheet used by operations                                                      |
| `sync_state.json`  | Previous synchronized state used for conflict detection                                  |
| `submission.json`  | Grader command configuration                                                             |
| `requirements.txt` | Python dependencies                                                                      |
| `.env`             | Local API configuration                                                                  |

---

# Setup

## Requirements

Python 3 is required.

Install dependencies:

```bash
pip install -r requirements.txt
```

Recommended dependencies:

* `requests`
* `openpyxl`
* `python-dotenv`

---

## Environment Variables

Create a `.env` file in the project root for local development:

```env
FIELDOPS_BASE_URL=http://13.233.55.184:8377
FIELDOPS_API_KEY=YOUR_PERSONAL_API_KEY
```

The API key is used as the HTTP Basic Authentication username.

The password is an arbitrary value as specified by the assignment.

For example:

```text
username = FIELDOPS_API_KEY
password = x
```

The grader supplies the required environment variables directly.

---

# Running the Application

## Full synchronization

Run:

```bash
python3 sync.py
```

One execution performs one complete synchronization cycle and then exits.

The synchronization cycle:

```text
FieldServe API
      |
      v
Fetch agents and tickets
      |
      v
Compare server state with previous sync state
      |
      +----------------------+
      |                      |
      v                      v
Server changes          Sheet changes
      |                      |
      v                      v
Update Excel            Update API
      |                      |
      +----------+-----------+
                 |
                 v
          Recalculate workflow
                 |
                 v
          Save Excel + state
```

---

# Spreadsheet

The real spreadsheet is:

```text
fieldserve.xlsx
```

The required columns are:

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

The spreadsheet is not a custom web UI. It is a real Excel workbook.

---

# Sheet CLI

The grader interacts with the spreadsheet through `sheet.py`.

## Export

```bash
python3 sheet.py export /tmp/out.csv
```

This exports the current spreadsheet values to CSV.

The first row contains the required column headers.

Computed values such as:

```text
Stage
Action Owner
```

are exported as their displayed values.

---

## Apply edits

```bash
python3 sheet.py apply /tmp/edits.csv
```

The input CSV format is:

```csv
Ticket ID,Column,Value
581102,Engineer,Ginarkin Sipu
607702,Purchase Order,https://example.com/po/607702
```

Only these columns are editable:

```text
Status
Engineer
Manager
Purchase Order
Delivery Note
Work Report
Invoice
```

`sheet.py apply` only changes the local Excel workbook.

It does **not** call the API and does **not** run synchronization.

The next:

```bash
python3 sync.py
```

will synchronize those changes.

---

# Workflow

The workflow is evaluated in this exact order:

```text
1. Assign Manager
2. Assign Engineer
3. Purchase Order
4. Delivery Note
5. Work Report
6. Invoice
```

The first unmet step becomes the ticket's:

```text
Stage
```

The person responsible for that step becomes:

```text
Action Owner
```

If every step is complete:

```text
Stage = Done
Action Owner = blank
```

---

## Assign Manager

A ticket has completed the manager-assignment step when:

```text
manager
```

is non-empty.

The coordinator owns this step.

Coordinator ownership is determined using the ticket ID parity rule from the assignment.

---

## Assign Engineer

A ticket has completed the engineer-assignment step when:

```text
engineer_id
```

is set.

The manager owns this step.

---

## Purchase Order

Purchase Order is complete only when:

```text
purchase_order = URL
```

`NA` does not waive Purchase Order.

The manager owns this step.

---

## Delivery Note

Delivery Note is complete when either:

```text
delivery_note = URL
```

or:

```text
delivery_note = NA
```

Finance owns this step.

---

## Work Report

Work Report is complete only when:

```text
work_report = URL
```

It cannot be waived with `NA`.

The assigned engineer owns this step.

---

## Invoice

Invoice is complete when either:

```text
invoice = URL
```

or:

```text
invoice = NA
```

Finance owns this step.

---

# Document Validation

Document fields accept only:

```text
URL
empty
NA
```

Any other text is considered junk and does not satisfy the workflow requirement.

Examples:

```text
https://example.com/document.pdf
```

counts as a document.

```text
NA
```

is a valid waiver where the workflow allows it.

```text
waiting for approval
```

does not count.

---

# Status Mapping

The API uses numeric status values.

They are represented in the spreadsheet as:

| API value | Spreadsheet value |
| --------: | ----------------- |
|       `2` | Open              |
|       `3` | Pending           |
|       `4` | Resolved          |
|       `5` | Closed            |

---

# Integrity

The synchronization logic also checks workflow integrity.

Examples include:

* Manager name does not exist in the manager roster.
* Engineer ID does not exist in the engineer roster.
* Engineer ID references a non-engineer.
* Document field contains invalid/junk text.
* A Closed ticket is missing a required workflow step.
* A Resolved ticket is missing its Work Report.

Integrity information is calculated internally by the workflow engine and can be used to identify problematic tickets.

---

# Conflict Policy

The synchronization uses an explicit:

```text
Server Wins
```

policy for conflicts on the same field.

The previous synchronized state is stored in:

```text
sync_state.json
```

For every editable field, the synchronizer compares:

```text
Previous synchronized value
Current Excel value
Current API value
```

## Sheet-only change

Example:

```text
Previous:
Manager = "Nefo Zagi"

Excel:
Manager = "Felboso Hamar"

API:
Manager = "Nefo Zagi"
```

Only the spreadsheet changed.

The change is pushed to the API.

---

## Server-only change

Example:

```text
Previous:
Purchase Order = old URL

Excel:
Purchase Order = old URL

API:
Purchase Order = new URL
```

Only the server changed.

The new server value is written into Excel.

---

## Both sides changed

Example:

```text
Previous:
Manager = "Nefo Zagi"

Excel:
Manager = "Felboso Hamar"

API:
Manager = "Pahifan Kinga"
```

Both sides changed the same field since the previous synchronization.

The server value wins.

Therefore:

```text
Excel after sync:
Manager = "Pahifan Kinga"
```

The local conflicting value is not silently pushed over the fresh server value.

---

# New Tickets

New tickets returned by the API are added to the spreadsheet.

Their:

* Ticket ID
* Subject
* Status
* Engineer
* Manager
* Documents
* Stage
* Action Owner

are calculated from the server ticket.

---

# API Synchronization

The API client uses:

```text
GET /api/v2/agents
GET /api/v2/tickets
GET /api/v2/tickets/{id}
PUT /api/v2/tickets/{id}
```

The ticket list supports:

```text
page
per_page
updated_since
```

The implementation uses:

```text
per_page = 50
```

and handles the API's page/window limitation using `updated_since`.

The API is documented as returning tickets ordered by:

```text
updated_at ascending
```

This allows synchronization to advance through large datasets using an updated-time cursor.

---

# API Rate Limiting

The API has a documented rate limit of:

```text
60 requests/minute
```

When the API responds with:

```text
429 Too Many Requests
```

the client checks:

```text
Retry-After
```

and waits before retrying.

A bounded retry count is used so synchronization does not retry forever.

---

# Messy Data

The API data may contain inconsistent or noisy information.

## Store Code

The store code is extracted from the subject or requester email.

The expected format is:

```text
6 alphanumeric characters
```

For example:

```text
M9GDCU
```

---

## Work Type

Work type is classified as:

```text
PM / AMC             -> Maintenance
Installation         -> Installation
Fault / not working /
complaint            -> Service Call
Anything else        -> Other
```

The original API subject is preserved in the spreadsheet.

---

# Noise Tickets

The implementation uses conservative noise detection for obvious:

* automated alerts
* marketing/promotional messages
* spam/test messages

Noise exclusion is intentionally conservative so legitimate operational tickets are not accidentally removed.

---

# Engineer and Manager Validation

`engineer_id` is treated as a foreign key into the agent roster.

The Engineer value displayed in Excel is the exact agent name from the roster.

The Manager field is stored by the API as a plain name string.

Manager names are validated against the manager roster before spreadsheet edits are pushed back to the API.

---

# API Credentials

Do not commit the personal API key to source control.

The local `.env` file should not be committed.

The repository should contain the code only; credentials should be supplied through environment variables.

---

# Testing

The system should be tested in both directions.

## 1. Initial synchronization

```bash
python3 sync.py
```

Then:

```bash
python3 sheet.py export /tmp/out.csv
```

Inspect:

```text
/tmp/out.csv
```

---

## 2. Spreadsheet-to-API test

Create an edits file:

```csv
Ticket ID,Column,Value
581102,Engineer,Ginarkin Sipu
```

Apply it:

```bash
python3 sheet.py apply /tmp/edits.csv
```

Then synchronize:

```bash
python3 sync.py
```

The API should receive the edit.

---

## 3. API-to-spreadsheet test

Change a ticket on the API side, then run:

```bash
python3 sync.py
```

Export:

```bash
python3 sheet.py export /tmp/out.csv
```

The spreadsheet should contain the server-side change.

---

## 4. Conflict test

Change one field on the spreadsheet and change the same field on the server before running synchronization.

Then:

```bash
python3 sync.py
```

The documented policy is:

```text
Server wins
```

The spreadsheet should contain the server value after synchronization.

---

## 5. Workflow tests

Test tickets covering:

```text
Missing Manager
Missing Engineer
Missing Purchase Order
Missing Delivery Note
Missing Work Report
Missing Invoice
NA Delivery Note
NA Invoice
Closed with missing paperwork
Resolved without Work Report
All steps complete
```

The Stage and Action Owner should follow the workflow order.

---

# Submission Commands

The submission configuration is:

```json
{
  "sync_cmd": "python3 sync.py",
  "sheet_cmd": "python3 sheet.py"
}
```

Both commands are intended to be executed from the repository root.

---

# Assumptions

1. The FieldServe API is the source of truth for ticket identity and server-side ticket data.
2. Excel is the operational working copy used by humans.
3. `sync_state.json` represents the last successfully synchronized state.
4. When both sides change the same field, the server value wins.
5. The Engineer spreadsheet value is resolved from `engineer_id`.
6. Manager names are validated against the agent roster.
7. Document fields only count when they contain a valid URL or an allowed `NA` waiver.
8. Noise detection is conservative.
9. Computed workflow fields are derived from the current ticket state rather than manually edited.
10. A successful synchronization updates the spreadsheet and synchronization state together.

---

# Future Work

Possible improvements outside the assignment timebox include:

* More sophisticated noise classification.
* More detailed audit logging.
* A visible conflict/audit sheet.
* Better incremental synchronization state management.
* Automated scheduled synchronization.
* Additional spreadsheet validation/drop-downs.
* More comprehensive automated tests.
* Operational metrics and dashboards.

```

This completes the **README**.

At this point, the main code/configuration files are all present. The next step should **not** be another code file—we should first run the project and see what actually happens, because `sync.py` is where the modules interact and integration issues can surface.
```
