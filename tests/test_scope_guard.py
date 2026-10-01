"""
H1 (QA report, high): a named territory/region outside the user's scope must get an
honest access-denied message, not a fabricated "no sales due to market conditions"
answer. These tests exercise app.scope_guard.find_out_of_scope_mention directly — no
Bedrock/network needed, only the local DB's zip_territory reference data.
"""

from app.scope_guard import find_out_of_scope_mention


def test_exec_never_flagged_regardless_of_question():
    assert find_out_of_scope_mention(
        "Show me sales in Texas and the West region", "exec", None, None
    ) is None


def test_ram_own_territory_mention_not_flagged():
    assert find_out_of_scope_mention(
        "How is New York Metro doing this quarter?", "ram", "New York Metro", "Northeast"
    ) is None


def test_ram_no_place_named_not_flagged():
    assert find_out_of_scope_mention(
        "What are my top accounts by volume this quarter?",
        "ram", "New York Metro", "Northeast",
    ) is None


def test_ram_other_territory_flagged():
    """QA report's literal repro: RAM asking about a territory that isn't theirs."""
    msg = find_out_of_scope_mention(
        "Show me sales in Texas", "ram", "New York Metro", "Northeast"
    )
    assert msg is not None
    assert "Texas" in msg
    assert "New York Metro" in msg  # offers their own scope instead


def test_ram_other_region_flagged():
    msg = find_out_of_scope_mention(
        "Show me sales for the West region", "ram", "New York Metro", "Northeast"
    )
    assert msg is not None
    assert "West" in msg
    assert "New York Metro" in msg


def test_ram_california_south_repro_from_report():
    """QA report's literal example: 'Show me sales in California South'."""
    msg = find_out_of_scope_mention(
        "Show me sales in California South", "ram", "New York Metro", "Northeast"
    )
    assert msg is not None
    assert "California South" in msg


def test_director_territory_within_own_region_not_flagged():
    """A Director's scope is their whole region - a territory inside it is in scope."""
    assert find_out_of_scope_mention(
        "How is New England doing?", "director", None, "Northeast"
    ) is None


def test_director_own_region_mention_not_flagged():
    assert find_out_of_scope_mention(
        "How is the Northeast region doing this quarter?", "director", None, "Northeast"
    ) is None


def test_director_other_region_flagged():
    """QA report's literal repro: Director asking about a region that isn't theirs."""
    msg = find_out_of_scope_mention(
        "Show me sales for the West region", "director", None, "Northeast"
    )
    assert msg is not None
    assert "West" in msg
    assert "Northeast" in msg


def test_director_territory_in_another_region_flagged():
    msg = find_out_of_scope_mention(
        "Show me Texas sales", "director", None, "Northeast"
    )
    assert msg is not None
    assert "Texas" in msg
    assert "Northeast" in msg
