"""family-conflicts: deterministic conflict detection and resolution ranking for households."""
from .engine import (
    Appt,
    Conflict,
    Option,
    Person,
    Rule,
    apply_option,
    covered,
    describe_rule,
    detect,
    fmt_day,
    fmt_time,
    free_slots,
    overlaps,
    parents_free_for,
    suggest,
    task_matches,
    violates,
)

__all__ = [
    "Appt", "Conflict", "Option", "Person", "Rule", "apply_option", "covered", "describe_rule",
    "detect", "fmt_day", "fmt_time", "free_slots", "overlaps", "parents_free_for", "suggest",
    "task_matches", "violates",
]
__version__ = "0.1.0"
