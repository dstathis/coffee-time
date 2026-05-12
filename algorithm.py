"""
Matching algorithm for the Coffee Exchange app.

Uses PuLP to solve an Integer Linear Program (ILP) that assigns bags to
recipients while respecting hard constraints and optimising for preference
satisfaction, source diversity, and variety.

See SPEC.md § Matching Algorithm for the full specification.

Overview of the ILP formulation
-------------------------------

Decision variables:
  x[b, p] ∈ {0, 1}  — 1 if bag b is assigned to person p.

Hard constraints:
  1. Each bag is assigned to exactly one person.
    2. Each person receives exactly as many bags as they submitted.
  3. No person receives a bag they brought.

Objective (maximise):
  Weighted sum of three components:

  - PREF_WEIGHT   (high)  : +1 per trait match on a strict preference.
                             "both" preferences contribute 0 — they are
                             treated as "no preference" and do not attract
                             or repel any bag.

  - DIVERSITY_WEIGHT (med): Penalise receiving multiple bags from the same
                             source person.  Implemented via auxiliary
                             binary variables y[p, s] that indicate
                             whether person p receives ≥1 bag from source s.
                             Maximising Σ y[p, s] rewards spreading.

  - VARIETY_WEIGHT  (low) : For recipients with "both" on a trait, give a
                             small bonus for receiving a mix of trait
                             values (at least one of each).

Weight constants are chosen so that priorities never conflict:
  PREF_WEIGHT >> DIVERSITY_WEIGHT >> VARIETY_WEIGHT.
"""

from __future__ import annotations

from dataclasses import dataclass

import pulp


# ---------------------------------------------------------------------------
# Weight constants — ratios ensure strict priority ordering.
# ---------------------------------------------------------------------------

# Points per strict-preference match (brew or process).
PREF_WEIGHT = 100
# Points per distinct source person a recipient receives from.
DIVERSITY_WEIGHT = 10
# Points for having a mix of trait values when preference is "both".
VARIETY_WEIGHT = 1


# ---------------------------------------------------------------------------
# Lightweight data containers passed into the solver so it has no dependency
# on SQLAlchemy models.
# ---------------------------------------------------------------------------


@dataclass
class BagData:
    """Flat representation of a bag for the solver."""

    id: int
    owner_id: int
    brew_method: str  # "filter" or "espresso"
    process: str  # "washed" or "natural"


@dataclass
class PersonData:
    """Flat representation of a person for the solver."""

    id: int
    name: str
    pref_brew: str  # "filter", "espresso", or "both"
    pref_process: str  # "washed", "natural", or "both"


@dataclass
class AssignmentResult:
    """One bag→recipient assignment produced by the solver."""

    bag_id: int
    recipient_id: int


# ---------------------------------------------------------------------------
# Preference-match scoring helper
# ---------------------------------------------------------------------------


def _pref_score(bag: BagData, person: PersonData) -> int:
    """
    Return a preference score for assigning *bag* to *person*.

    Each trait (brew method, process) scores independently:
      - Strict preference matches the bag's trait  → +PREF_WEIGHT
      - Strict preference does NOT match           → 0  (no penalty in
        objective; the solver simply won't favour it)
      - "both" preference                          → 0  (neutral)

    Returns the sum over both traits.
    """
    score = 0
    # Brew method
    if person.pref_brew != "both" and bag.brew_method == person.pref_brew:
        score += PREF_WEIGHT
    # Process
    if person.pref_process != "both" and bag.process == person.pref_process:
        score += PREF_WEIGHT
    return score


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def solve(
    people: list[PersonData], bags: list[BagData]
) -> list[AssignmentResult]:
    """
    Run the matching algorithm and return a list of assignments.

    Parameters
    ----------
    people : list[PersonData]
        All participants.  Each must have brought at least one bag present
        in *bags*.
    bags : list[BagData]
        All bags across all participants.

    Returns
    -------
    list[AssignmentResult]
        One entry per bag, mapping it to a recipient.

    Raises
    ------
    RuntimeError
        If the solver fails to find a feasible solution (should not happen
        with valid input, but guarded against).
    """

    # Convenience lookups.
    person_ids = [p.id for p in people]
    bag_ids = [b.id for b in bags]
    bag_by_id = {b.id: b for b in bags}
    person_by_id = {p.id: p for p in people}
    bags_required_by_person = {
        p_id: sum(1 for b in bags if b.owner_id == p_id)
        for p_id in person_ids
    }

    # Distinct source (owner) ids for each bag, used for diversity.
    owner_ids = sorted({b.owner_id for b in bags})

    # -- Create the ILP problem ------------------------------------------------

    prob = pulp.LpProblem("CoffeeExchange", pulp.LpMaximize)

    # Decision variables: x[bag_id, person_id] ∈ {0, 1}
    x = pulp.LpVariable.dicts(
        "x", (bag_ids, person_ids), cat=pulp.LpBinary
    )

    # -- Hard constraints ------------------------------------------------------

    # C1: Each bag is assigned to exactly one person.
    for b in bag_ids:
        prob += (
            pulp.lpSum(x[b][p] for p in person_ids) == 1,
            f"bag_{b}_assigned_once",
        )

    # C2: Each person receives as many bags as they submitted.
    for p in person_ids:
        required = bags_required_by_person[p]
        prob += (
            pulp.lpSum(x[b][p] for b in bag_ids) == required,
            f"person_{p}_gets_{required}",
        )

    # C3: No person receives their own bag.
    for b in bags:
        prob += (
            x[b.id][b.owner_id] == 0,
            f"no_self_{b.id}",
        )

    # -- Auxiliary variables for diversity -------------------------------------
    #
    # y[p, s] ∈ {0, 1}: 1 if person p receives at least one bag from
    # source person s.  We link y to x with:
    #   y[p, s] <= Σ x[b][p]  for all bags b owned by s
    #   y[p, s] >= x[b][p]    for each such b  (not needed for maximisation
    #                          — the solver will set y=1 when beneficial)
    # Since we're maximising Σ y, the solver will set y[p,s]=1 whenever any
    # x[b][p]=1 for a bag b owned by s.  The upper-bound constraint ensures
    # y can't be 1 unless at least one such bag is assigned.

    y = pulp.LpVariable.dicts(
        "y", (person_ids, owner_ids), cat=pulp.LpBinary
    )

    # Bags grouped by owner for convenience.
    bags_by_owner: dict[int, list[int]] = {}
    for b in bags:
        bags_by_owner.setdefault(b.owner_id, []).append(b.id)

    for p in person_ids:
        for s in owner_ids:
            source_bags = bags_by_owner.get(s, [])
            # y[p][s] can be 1 only if person p receives ≥1 bag from s.
            prob += (
                y[p][s] <= pulp.lpSum(x[b][p] for b in source_bags),
                f"diversity_ub_{p}_{s}",
            )

    # -- Auxiliary variables for variety (for "both" preferences) --------------
    #
    # For each person with pref_brew == "both", we add binary variables
    # indicating whether they receive at least one filter and at least one
    # espresso bag.  Similarly for pref_process == "both".
    #
    # v_brew_filter[p], v_brew_espresso[p]: 1 if person p receives ≥1 bag
    #   of that brew method.
    # v_proc_washed[p], v_proc_natural[p]: likewise for process.
    #
    # Bonus = VARIETY_WEIGHT for each of these that is 1.

    variety_vars: list[pulp.LpVariable] = []

    for p_data in people:
        p = p_data.id
        if p_data.pref_brew == "both":
            for method in ("filter", "espresso"):
                v = pulp.LpVariable(
                    f"v_brew_{method}_{p}", cat=pulp.LpBinary
                )
                method_bags = [
                    b.id for b in bags if b.brew_method == method
                ]
                prob += (
                    v <= pulp.lpSum(x[b][p] for b in method_bags),
                    f"variety_brew_{method}_ub_{p}",
                )
                variety_vars.append(v)

        if p_data.pref_process == "both":
            for proc in ("washed", "natural"):
                v = pulp.LpVariable(
                    f"v_proc_{proc}_{p}", cat=pulp.LpBinary
                )
                proc_bags = [b.id for b in bags if b.process == proc]
                prob += (
                    v <= pulp.lpSum(x[b][p] for b in proc_bags),
                    f"variety_proc_{proc}_ub_{p}",
                )
                variety_vars.append(v)

    # -- Objective function ----------------------------------------------------

    # Component 1: Preference matching.
    pref_obj = pulp.lpSum(
        _pref_score(bag_by_id[b], person_by_id[p]) * x[b][p]
        for b in bag_ids
        for p in person_ids
    )

    # Component 2: Source diversity.
    diversity_obj = pulp.lpSum(
        y[p][s] for p in person_ids for s in owner_ids
    )

    # Component 3: Variety for "both" preferences.
    variety_obj = pulp.lpSum(variety_vars)

    prob += (
        pref_obj
        + DIVERSITY_WEIGHT * diversity_obj
        + VARIETY_WEIGHT * variety_obj,
        "total_objective",
    )

    # -- Solve -----------------------------------------------------------------

    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    if prob.status != pulp.constants.LpStatusOptimal:
        raise RuntimeError(
            f"Solver did not find an optimal solution (status={prob.status})."
        )

    # -- Extract results -------------------------------------------------------

    results: list[AssignmentResult] = []
    for b in bag_ids:
        for p in person_ids:
            if pulp.value(x[b][p]) > 0.5:  # binary, so 1.0
                results.append(AssignmentResult(bag_id=b, recipient_id=p))
                break  # each bag assigned to exactly one person

    return results
