# Coffee Exchange

A web app for organising a coffee bag exchange among friends. Each participant
brings 3 bags of coffee and receives 3 bags from other participants, matched
to their preferences using an optimisation algorithm.

See [SPEC.md](SPEC.md) for the full design specification.

## Quick Start

```bash
# 1. Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure credentials
cp .env.example .env
# Edit .env with your chosen passwords

# 4. Run the app
python app.py
```

The app starts on `http://localhost:5000`.

## Environment Variables

| Variable         | Required | Description                        |
| ---------------- | -------- | ---------------------------------- |
| `APP_USERNAME`   | Yes      | HTTP Basic Auth username           |
| `APP_PASSWORD`   | Yes      | HTTP Basic Auth password           |
| `ADMIN_PASSWORD` | Yes      | Password for the admin dashboard   |
| `SECRET_KEY`     | No       | Flask session key (auto-generated) |
| `DATABASE_URL`   | No       | SQLite file path (default: `coffee.db`) |

## How It Works

1. Share the app URL and Basic Auth credentials with your friends.
2. Each person submits their name, 3 bags of coffee (with brew method,
   process, and optional description), and their preferences.
3. Once everyone has submitted, the admin logs in and runs the matching
   algorithm.
4. The results page shows who gives which bags to whom.

## Project Structure

```
coffee-time/
├── app.py           # Flask application and routes
├── models.py        # SQLAlchemy database models
├── auth.py          # Authentication helpers
├── algorithm.py     # PuLP-based matching algorithm
├── requirements.txt # Python dependencies
├── .env.example     # Example environment configuration
├── SPEC.md          # Full design specification
├── static/
│   └── style.css    # Custom responsive CSS
└── templates/
    ├── base.html        # Base layout template
    ├── index.html       # Participant submission form
    ├── locked.html      # Shown when submissions are closed
    ├── results.html     # Assignment results display
    ├── admin_login.html # Admin login form
    ├── admin.html       # Admin dashboard
    └── admin_edit.html  # Admin edit participant form
```
