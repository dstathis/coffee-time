# Coffee Exchange App — Specification

## Overview

A web app to facilitate a coffee bag exchange among friends. Each participant
brings one or more bags of coffee and receives the same number from other participants. The app
collects bag traits and personal preferences, then runs an optimisation
algorithm to determine the best assignment of bags to people.

## Tech Stack

| Component       | Choice                                    |
| --------------- | ----------------------------------------- |
| Language        | Python 3.10+                              |
| Web framework   | Flask                                     |
| Database        | SQLite via SQLAlchemy                      |
| Templating      | Jinja2 (server-side rendered)             |
| Styling         | Custom hand-written CSS (mobile-first)    |
| Optimisation    | PuLP (CBC solver)                         |
| Env config      | python-dotenv                             |

## Authentication

### App-wide Basic Auth

All routes are protected by HTTP Basic Auth. Credentials are set via
environment variables:

- `APP_USERNAME` — shared username for all participants
- `APP_PASSWORD` — shared password for all participants

### Admin Auth

The admin page (`/admin`) requires an additional password (`ADMIN_PASSWORD`
env var) entered via a login form. The admin session is stored in a
server-side Flask session.

## Data Model

### Person

| Field | Type        | Constraints   | Description                    |
| ----- | ----------- | ------------- | ------------------------------ |
| id    | Integer     | PK            | Auto-incrementing primary key  |
| name  | String(100) | Unique, NN    | Participant display name       |
| pref_brew | String(10) | NN         | "filter", "espresso", or "both"|
| pref_process | String(10) | NN      | "washed", "natural", or "both" |

### Bag

| Field       | Type        | Constraints | Description                       |
| ----------- | ----------- | ----------- | --------------------------------- |
| id          | Integer     | PK          | Auto-incrementing primary key     |
| person_id   | Integer     | FK → Person | Who brought this bag              |
| brew_method | String(10)  | NN          | "filter" or "espresso"            |
| process     | String(10)  | NN          | "washed" or "natural"             |
| description | String(200) | Nullable    | Optional name / origin / roaster  |

Each person must have at least 1 bag.

### Assignment

| Field       | Type    | Constraints | Description                      |
| ----------- | ------- | ----------- | -------------------------------- |
| id          | Integer | PK          | Auto-incrementing primary key    |
| bag_id      | Integer | FK → Bag    | The bag being assigned           |
| recipient_id| Integer | FK → Person | Who receives this bag            |

### AppState

A single-row table to track global state:

| Field            | Type    | Description                          |
| ---------------- | ------- | ------------------------------------ |
| id               | Integer | Always 1                             |
| algorithm_has_run | Boolean | Whether assignments have been made  |

## User Flow

### Participant Submission (single page)

1. Participant visits `/` — sees a form with:
   - Name field
  - One or more bag sections, each with: brew method (filter/espresso), process
     (washed/natural), description (optional text)
   - Preferences: brew method (filter/espresso/both), process
     (washed/natural/both)
2. If the name already exists in the database, the form is pre-filled with
   their existing data for editing.
3. On submit, data is validated and saved (insert or update).
4. After the algorithm has been run, submissions are **locked** — the form
   is replaced with a "submissions are closed" message.

### Admin Page (`/admin`)

- Protected by a separate password entered via a login form.
- Shows a list of all participants with their bags and preferences.
- Allows editing and deleting any participant.
- "Run Algorithm" button triggers the matching algorithm.
  - If assignments already exist, a confirmation prompt is shown before
    overwriting.
- Admin can still edit/delete entries after the algorithm has run (and
  re-run the algorithm).

### Results Page (`/results`)

- Publicly accessible (within the Basic Auth boundary).
- Shows the full assignment matrix: who gives which bag to whom.
- Flags any bag that does not match the recipient's stated preference.
- If the algorithm hasn't been run yet, shows a "results not available yet"
  message.

## Matching Algorithm

Implemented as an Integer Linear Program using PuLP.

### Decision Variables

- `x[b][p]` ∈ {0, 1} — whether bag `b` is assigned to person `p`.

### Hard Constraints

1. Each bag is assigned to exactly one person.
2. Each person receives exactly as many bags as they submitted.
3. No person receives their own bag.

### Objective (maximise)

Weighted sum of:

1. **Preference matching (highest weight):** For each assignment, score
   points when the bag's traits match the recipient's strict preferences.
   "both" preferences score 0 (neither penalised nor rewarded — treated as
   no preference).

2. **Source diversity (medium weight):** Penalise when a person receives
   multiple bags from the same source. Encourages bags from different
   people.

3. **Variety for "both" preferences (lowest weight):** For recipients with
   "both" on a trait, give a small bonus for receiving a mix of values
   (e.g., some washed and some natural).

### Edge Cases

- If preferences are mathematically impossible to fully satisfy, the solver
  finds the best-effort solution.
- Mismatched assignments are flagged on the results page.

## Configuration

All via environment variables (`.env` file supported via python-dotenv):

| Variable         | Required | Description                        |
| ---------------- | -------- | ---------------------------------- |
| `APP_USERNAME`   | Yes      | Basic auth username                |
| `APP_PASSWORD`   | Yes      | Basic auth password                |
| `ADMIN_PASSWORD` | Yes      | Password for the admin page        |
| `SECRET_KEY`     | No       | Flask session secret (random default) |
| `DATABASE_URL`   | No       | SQLite path (default: `coffee.db`) |

## Routes

| Method | Path              | Description                        |
| ------ | ----------------- | ---------------------------------- |
| GET    | `/`               | Submission form (or locked message)|
| POST   | `/`               | Submit / update entry              |
| GET    | `/results`        | Public results page                |
| GET    | `/admin`          | Admin login or dashboard           |
| POST   | `/admin/login`    | Admin login handler                |
| POST   | `/admin/delete/<id>` | Delete a participant            |
| GET    | `/admin/edit/<id>`| Edit form for a participant        |
| POST   | `/admin/edit/<id>`| Save edits for a participant       |
| POST   | `/admin/run`      | Trigger the matching algorithm     |
| GET    | `/admin/logout`   | Clear admin session                |
