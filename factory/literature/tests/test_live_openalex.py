from __future__ import annotations

import os

import pytest

from factory.literature.api import OpenAlexClient


@pytest.mark.live
def test_live_seed_search() -> None:
    if not os.environ.get("OPENALEX_API_KEY"):
        pytest.skip("OPENALEX_API_KEY is required for live OpenAlex seed search")

    client = OpenAlexClient()
    works = client.search_works(
        "quasi isodynamic stellarator",
        {"open_access.is_oa": True},
        limit=1,
    )

    assert len(works) == 1
    assert works[0].work_id.startswith("W")
    assert works[0].is_open_access is True
    assert works[0].title
