"""
Coffee Exchange — Flask application.

This is the main entry point. It defines all routes, wires up the database,
and applies authentication.  See SPEC.md for the full route table and
behavioural specification.

Run with:
    python app.py

Or via Flask CLI:
    flask run
"""

from __future__ import annotations

import os
import secrets

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from algorithm import AssignmentResult, BagData, PersonData, solve
from auth import require_admin, require_basic_auth, check_admin_password
from models import AppState, Assignment, Bag, Person, db

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

load_dotenv()  # Load .env file if present.


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # -- Configuration ---------------------------------------------------------

    db_path = os.environ.get("DATABASE_URL", "coffee.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", secrets.token_hex(32)
    )

    # -- Database init ---------------------------------------------------------

    db.init_app(app)
    with app.app_context():
        db.create_all()

    # -- Apply Basic Auth to ALL routes ----------------------------------------

    @app.before_request
    def _enforce_basic_auth() -> None:
        """
        Check HTTP Basic Auth on every request.

        This runs before any route handler.  If credentials are missing or
        wrong the user sees the browser's built-in login dialog.
        """
        # Use the decorator logic inline so we can return a Response.
        from flask import Response

        auth = request.authorization
        if not auth or not __import__("auth").check_basic_auth(
            auth.username, auth.password
        ):
            # Abort with 401 — browser will prompt for credentials.
            response = Response(
                "Authentication required.",
                401,
                {"WWW-Authenticate": 'Basic realm="Coffee Exchange"'},
            )
            # Flask's before_request can short-circuit by returning a response.
            from flask import abort
            abort(response)

    # -- Routes ----------------------------------------------------------------

    # ---- Home page -----------------------------------------------------------

    @app.route("/")
    def home():
        """
        Home page showing all submissions.

        Displays the participant list (names, bags, preferences) without
        action buttons.  When the algorithm has run, shows a banner
        linking to results instead of the submit button.
        """
        people = Person.query.order_by(Person.name).all()
        state = AppState.get()
        return render_template("home.html", people=people, state=state)

    # ---- Participant submission page -----------------------------------------

    @app.route("/submit", methods=["GET", "POST"])
    def submit():
        """
        GET  → show the submission form (or a "locked" message if the
               algorithm has already run).
        POST → validate and save/update the participant's entry.
        """
        state = AppState.get()

        # If algorithm has run, show locked page.
        if state.algorithm_has_run:
            return render_template("locked.html")

        if request.method == "POST":
            return _handle_submission()

        # GET — render blank or pre-filled form.
        name = request.args.get("name", "").strip()
        person = Person.query.filter_by(name=name).first() if name else None
        return render_template("index.html", person=person)

    def _handle_submission():
        """Process the participant submission form."""
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name is required.", "error")
            return redirect(url_for("submit"))

        # Preferences.
        pref_brew = request.form.get("pref_brew", "both")
        pref_process = request.form.get("pref_process", "both")

        # Validate preference values.
        if pref_brew not in ("filter", "espresso", "both"):
            flash("Invalid brew preference.", "error")
            return redirect(url_for("submit"))
        if pref_process not in ("washed", "natural", "both"):
            flash("Invalid process preference.", "error")
            return redirect(url_for("submit"))

        # Collect bag data from the form.
        bag_data = []
        for i in range(1, 4):
            brew = request.form.get(f"bag{i}_brew", "")
            proc = request.form.get(f"bag{i}_process", "")
            desc = request.form.get(f"bag{i}_desc", "").strip()
            if brew not in ("filter", "espresso"):
                flash(f"Bag {i}: invalid brew method.", "error")
                return redirect(url_for("submit"))
            if proc not in ("washed", "natural"):
                flash(f"Bag {i}: invalid process.", "error")
                return redirect(url_for("submit"))
            bag_data.append((brew, proc, desc))

        # Upsert person.
        person = Person.query.filter_by(name=name).first()
        if person is None:
            person = Person(name=name)
            db.session.add(person)

        person.pref_brew = pref_brew
        person.pref_process = pref_process

        # Replace existing bags (delete old, add new).
        Bag.query.filter_by(person_id=person.id).delete()
        for brew, proc, desc in bag_data:
            bag = Bag(
                person_id=person.id,
                brew_method=brew,
                process=proc,
                description=desc,
            )
            db.session.add(bag)

        db.session.commit()
        flash(f"Submission saved for {name}!", "success")
        return redirect(url_for("home"))

    # ---- Results page --------------------------------------------------------

    @app.route("/results")
    def results():
        """
        Show the full assignment matrix.

        If the algorithm hasn't been run yet, show a "not available" message.
        Flags bags that don't match the recipient's preferences.
        """
        state = AppState.get()
        if not state.algorithm_has_run:
            return render_template("results.html", assignments=None)

        # Build a structured list for the template.
        assignments = (
            db.session.query(Assignment, Bag, Person)
            .join(Bag, Assignment.bag_id == Bag.id)
            .join(Person, Assignment.recipient_id == Person.id)
            .all()
        )

        # Group by recipient.
        from collections import defaultdict

        by_recipient: dict[int, dict] = {}
        for assignment, bag, recipient in assignments:
            if recipient.id not in by_recipient:
                by_recipient[recipient.id] = {
                    "person": recipient,
                    "bags": [],
                }
            owner = db.session.get(Person, bag.person_id)
            # Check for preference mismatches.
            brew_mismatch = (
                recipient.pref_brew != "both"
                and bag.brew_method != recipient.pref_brew
            )
            process_mismatch = (
                recipient.pref_process != "both"
                and bag.process != recipient.pref_process
            )
            by_recipient[recipient.id]["bags"].append(
                {
                    "bag": bag,
                    "from": owner,
                    "brew_mismatch": brew_mismatch,
                    "process_mismatch": process_mismatch,
                }
            )

        # Sort by recipient name for consistent display.
        grouped = sorted(
            by_recipient.values(), key=lambda r: r["person"].name.lower()
        )

        return render_template("results.html", assignments=grouped)

    # ---- Admin routes --------------------------------------------------------

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        """Admin login form and handler."""
        if request.method == "POST":
            password = request.form.get("password", "")
            if check_admin_password(password):
                session["is_admin"] = True
                return redirect(url_for("admin_dashboard"))
            flash("Invalid admin password.", "error")
        return render_template("admin_login.html")

    @app.route("/admin/logout")
    def admin_logout():
        """Clear admin session."""
        session.pop("is_admin", None)
        return redirect(url_for("home"))

    @app.route("/admin")
    @require_admin
    def admin_dashboard():
        """
        Admin dashboard: list all participants, their bags, and preferences.
        Provides controls to edit, delete, and run the algorithm.
        """
        people = Person.query.order_by(Person.name).all()
        state = AppState.get()
        return render_template(
            "admin.html", people=people, state=state
        )

    @app.route("/admin/delete/<int:person_id>", methods=["POST"])
    @require_admin
    def admin_delete(person_id: int):
        """Delete a participant and all their bags/assignments."""
        person = db.session.get(Person, person_id)
        if person:
            db.session.delete(person)
            db.session.commit()
            flash(f"Deleted {person.name}.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/edit/<int:person_id>", methods=["GET", "POST"])
    @require_admin
    def admin_edit(person_id: int):
        """Edit a participant's details (admin version of the form)."""
        person = db.session.get(Person, person_id)
        if not person:
            flash("Person not found.", "error")
            return redirect(url_for("admin_dashboard"))

        if request.method == "POST":
            # Update name.
            new_name = request.form.get("name", "").strip()
            if not new_name:
                flash("Name is required.", "error")
                return redirect(
                    url_for("admin_edit", person_id=person_id)
                )

            # Check name uniqueness (if changed).
            if new_name != person.name:
                existing = Person.query.filter_by(name=new_name).first()
                if existing:
                    flash(f'Name "{new_name}" is already taken.', "error")
                    return redirect(
                        url_for("admin_edit", person_id=person_id)
                    )

            person.name = new_name
            person.pref_brew = request.form.get("pref_brew", "both")
            person.pref_process = request.form.get("pref_process", "both")

            # Update bags.
            Bag.query.filter_by(person_id=person.id).delete()
            for i in range(1, 4):
                brew = request.form.get(f"bag{i}_brew", "filter")
                proc = request.form.get(f"bag{i}_process", "washed")
                desc = request.form.get(f"bag{i}_desc", "").strip()
                bag = Bag(
                    person_id=person.id,
                    brew_method=brew,
                    process=proc,
                    description=desc,
                )
                db.session.add(bag)

            db.session.commit()
            flash(f"Updated {person.name}.", "success")
            return redirect(url_for("admin_dashboard"))

        return render_template("admin_edit.html", person=person)

    @app.route("/admin/run", methods=["POST"])
    @require_admin
    def admin_run():
        """
        Trigger the matching algorithm.

        Deletes any existing assignments before running.  The admin is
        expected to confirm before calling this if results already exist
        (confirmation is handled client-side).
        """
        people = Person.query.all()
        bags = Bag.query.all()

        # Basic validation.
        if len(people) < 2:
            flash("Need at least 2 participants to run.", "error")
            return redirect(url_for("admin_dashboard"))

        for p in people:
            person_bags = [b for b in bags if b.person_id == p.id]
            if len(person_bags) != 3:
                flash(
                    f"{p.name} has {len(person_bags)} bags (need 3).",
                    "error",
                )
                return redirect(url_for("admin_dashboard"))

        # Convert to solver data structures.
        people_data = [
            PersonData(
                id=p.id,
                name=p.name,
                pref_brew=p.pref_brew,
                pref_process=p.pref_process,
            )
            for p in people
        ]
        bags_data = [
            BagData(
                id=b.id,
                owner_id=b.person_id,
                brew_method=b.brew_method,
                process=b.process,
            )
            for b in bags
        ]

        try:
            results = solve(people_data, bags_data)
        except RuntimeError as e:
            flash(f"Algorithm failed: {e}", "error")
            return redirect(url_for("admin_dashboard"))

        # Clear old assignments and save new ones.
        Assignment.query.delete()
        for r in results:
            db.session.add(
                Assignment(bag_id=r.bag_id, recipient_id=r.recipient_id)
            )

        # Mark algorithm as run.
        state = AppState.get()
        state.algorithm_has_run = True
        db.session.commit()

        flash("Algorithm ran successfully! Assignments are ready.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/unlock", methods=["POST"])
    @require_admin
    def admin_unlock():
        """Re-open submissions by clearing the algorithm_has_run flag."""
        state = AppState.get()
        state.algorithm_has_run = False
        # Optionally clear assignments too.
        Assignment.query.delete()
        db.session.commit()
        flash("Submissions are unlocked. Assignments have been cleared.", "success")
        return redirect(url_for("admin_dashboard"))

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=5000)
