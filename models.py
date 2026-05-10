"""
Database models for the Coffee Exchange app.

Tables:
  - Person:     A participant in the exchange (name + preferences).
  - Bag:        A bag of coffee brought by a person (traits + optional description).
  - Assignment: Maps a bag to the person who will receive it.
  - AppState:   Single-row table tracking global state (e.g. whether the
                algorithm has been run).

See SPEC.md for the full data-model documentation.
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Person(db.Model):
    """A participant in the coffee exchange."""

    __tablename__ = "person"

    id = db.Column(db.Integer, primary_key=True)
    # Display name — must be unique so participants can look up their entry.
    name = db.Column(db.String(100), unique=True, nullable=False)
    # Brew-method preference: "filter", "espresso", or "both".
    pref_brew = db.Column(db.String(10), nullable=False, default="both")
    # Process preference: "washed", "natural", or "both".
    pref_process = db.Column(db.String(10), nullable=False, default="both")

    # Relationship to the bags this person brought.
    bags = db.relationship(
        "Bag", backref="owner", lazy=True, cascade="all, delete-orphan"
    )
    # Relationship to assignments where this person is the recipient.
    received_assignments = db.relationship(
        "Assignment",
        backref="recipient",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Person {self.name!r}>"


class Bag(db.Model):
    """A bag of coffee brought by a participant."""

    __tablename__ = "bag"

    id = db.Column(db.Integer, primary_key=True)
    # Foreign key to the person who brought this bag.
    person_id = db.Column(
        db.Integer, db.ForeignKey("person.id"), nullable=False
    )
    # Brew method: "filter" or "espresso".
    brew_method = db.Column(db.String(10), nullable=False)
    # Processing method: "washed" or "natural".
    process = db.Column(db.String(10), nullable=False)
    # Optional free-text description (name, origin, roaster, etc.).
    description = db.Column(db.String(200), nullable=True, default="")

    # Relationship to assignment (a bag is assigned to at most one recipient).
    assignment = db.relationship(
        "Assignment",
        backref="bag",
        lazy=True,
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Bag {self.id} {self.brew_method}/{self.process}"
            f" from Person {self.person_id}>"
        )


class Assignment(db.Model):
    """Maps a bag to the person who will receive it."""

    __tablename__ = "assignment"

    id = db.Column(db.Integer, primary_key=True)
    # The bag being assigned.
    bag_id = db.Column(db.Integer, db.ForeignKey("bag.id"), nullable=False)
    # The person who will receive this bag.
    recipient_id = db.Column(
        db.Integer, db.ForeignKey("person.id"), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Assignment bag={self.bag_id} → person={self.recipient_id}>"


class AppState(db.Model):
    """
    Single-row table to store global application state.

    Only row id=1 is used. Created automatically on first run.
    """

    __tablename__ = "app_state"

    id = db.Column(db.Integer, primary_key=True)
    # True once the matching algorithm has been run and assignments exist.
    algorithm_has_run = db.Column(db.Boolean, nullable=False, default=False)

    @staticmethod
    def get() -> "AppState":
        """Return the singleton AppState row, creating it if necessary."""
        state = db.session.get(AppState, 1)
        if state is None:
            state = AppState(id=1, algorithm_has_run=False)
            db.session.add(state)
            db.session.commit()
        return state
