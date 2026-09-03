"""A backfill debt carries its own refusal budget.

The budget is what lets the pipeline force a debt closed without adding a human
touchpoint: collect retries the debt cells at most ``BACKFILL_RETRY_BUDGET`` targeted
rounds, and annotate's preflight refuses the corpus while any debt has budget left.
"""

import pytest
from pydantic import ValidationError

from newsab_schema.models import BACKFILL_RETRY_BUDGET, BackfillDebt


def debt(**overrides):
    return BackfillDebt(
        source_id="outlet", cell="all-cells", reason="engine walled", **overrides
    )


def test_defaults_are_a_fresh_debt():
    d = debt()
    assert (d.retries, d.retry_futile) == (0, False)
    assert not d.budget_exhausted
    assert d.key == "outlet:all-cells"


def test_budget_spends_exactly_at_the_cap():
    assert not debt(retries=BACKFILL_RETRY_BUDGET - 1).budget_exhausted
    assert debt(retries=BACKFILL_RETRY_BUDGET).budget_exhausted


def test_futile_counts_as_spent_immediately():
    assert debt(retry_futile=True).budget_exhausted


def test_negative_retries_are_rejected():
    with pytest.raises(ValidationError):
        debt(retries=-1)


def test_pre_t173_record_reads_as_fresh():
    # Records are immutable (§3.2): a debt written before the fields existed validates
    # with a full budget, so the gate fires on it rather than around it.
    d = BackfillDebt.model_validate(
        {"source_id": "telegraph_uk", "cell": "all-cells", "reason": "subscription wall"}
    )
    assert not d.budget_exhausted
