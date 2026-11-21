"""Evaluation harness (context.md §8).

Grades a redaction pipeline against the synthetic corpus (§7). This is the independent
grader for every downstream step, so it must be correct before any detector exists:
an incomplete extractor turns the leak test into a false green.
"""
