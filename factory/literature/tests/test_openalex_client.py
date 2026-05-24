from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pytest

from factory.literature.client import OpenAlexClient, OpenAlexResponse, OpenAlexTransport
from factory.literature.errors import OpenAlexAPIError, OpenAlexAuthError


@dataclass(frozen=True)
class RecordedRequest:
    endpoint: str
    params: Mapping[str, str]


class ScriptedTransport(OpenAlexTransport):
    def __init__(self, responses: tuple[OpenAlexResponse, ...]) -> None:
        self._responses = list(responses)
        self.requests: list[RecordedRequest] = []

    def get_json(self, endpoint: str, params: Mapping[str, str]) -> OpenAlexResponse:
        self.requests.append(RecordedRequest(endpoint=endpoint, params=dict(params)))
        return self._responses.pop(0)


def test_openalex_client_requires_api_key_and_rejects_obsolete_email_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.delenv("OPENALEX_EMAIL", raising=False)
    monkeypatch.delenv("OPENALEX_MAILTO", raising=False)
    with pytest.raises(OpenAlexAuthError, match="OPENALEX_API_KEY"):
        OpenAlexClient(transport=ScriptedTransport(()))

    monkeypatch.setenv("OPENALEX_API_KEY", "test-key")
    monkeypatch.setenv("OPENALEX_MAILTO", "ignored@example.com")
    OpenAlexClient(transport=ScriptedTransport(()))

    monkeypatch.setenv("OPENALEX_EMAIL", "old@example.com")
    with pytest.raises(OpenAlexAuthError, match="OPENALEX_EMAIL"):
        OpenAlexClient(transport=ScriptedTransport(()))


def test_parse_work_decodes_inverted_abstract_and_selected_fields() -> None:
    transport = ScriptedTransport((_ok(_work_payload("W1")),))
    client = OpenAlexClient(api_key="test-key", transport=transport)

    work = client.get_work("W1")

    assert work.work_id == "W1"
    assert work.abstract == "alpha beta gamma"
    assert work.referenced_work_ids == ("W2",)
    assert work.related_work_ids == ("W3",)
    assert work.is_open_access is True
    assert work.authors[0].name == "Ada Lovelace"
    assert transport.requests[0].params["api_key"] == "test-key"
    assert "abstract_inverted_index" in transport.requests[0].params["select"]


def test_parse_work_rejects_missing_required_live_fields() -> None:
    missing_title = _work_payload("W1")
    del missing_title["title"]
    del missing_title["display_name"]
    title_client = OpenAlexClient(
        api_key="test-key",
        transport=ScriptedTransport((_ok(missing_title),)),
    )
    with pytest.raises(OpenAlexAPIError, match="missing title/display_name"):
        title_client.get_work("W1")

    missing_citations = _work_payload("W2")
    del missing_citations["cited_by_count"]
    citation_client = OpenAlexClient(
        api_key="test-key",
        transport=ScriptedTransport((_ok(missing_citations),)),
    )
    with pytest.raises(OpenAlexAPIError, match="cited_by_count"):
        citation_client.get_work("W2")


def test_cursor_pagination_for_search_works() -> None:
    transport = ScriptedTransport(
        (
            _page((_work_payload("W1"),), next_cursor="cursor-2"),
            _page((_work_payload("W2"),), next_cursor=None),
        )
    )
    client = OpenAlexClient(api_key="test-key", transport=transport)

    works = client.search_works("stellarator", {"open_access.is_oa": True}, limit=2)

    assert tuple(work.work_id for work in works) == ("W1", "W2")
    assert transport.requests[0].params["cursor"] == "*"
    assert transport.requests[1].params["cursor"] == "cursor-2"
    assert transport.requests[0].params["per_page"] == "2"
    assert transport.requests[0].params["filter"] == "open_access.is_oa:true"
    assert transport.requests[0].params["sort"] == "relevance_score:desc"


def test_forward_citations_use_cites_filter() -> None:
    transport = ScriptedTransport((_page((_work_payload("W9"),), next_cursor=None),))
    client = OpenAlexClient(api_key="test-key", transport=transport)

    citations = client.get_forward_citations("W1", limit=10, max_pages=1)

    assert citations == ("W9",)
    assert transport.requests[0].endpoint == "/works"
    assert transport.requests[0].params["filter"] == "cites:W1"
    assert transport.requests[0].params["sort"] == "cited_by_count:desc"


def test_batch_get_works_splits_openalex_or_filter_at_one_hundred() -> None:
    first_page = tuple(_work_payload(f"W{i}") for i in range(100))
    second_page = (_work_payload("W100"),)
    transport = ScriptedTransport(
        (
            _page(first_page, next_cursor=None),
            _page(second_page, next_cursor=None),
        )
    )
    client = OpenAlexClient(api_key="test-key", transport=transport)

    works = client.batch_get_works(tuple(f"W{i}" for i in range(101)))

    assert len(works) == 101
    assert transport.requests[0].params["filter"].count("|") == 99
    assert transport.requests[1].params["filter"] == "openalex:W100"


def test_client_retries_rate_limit_and_server_errors_without_retrying_bad_request() -> None:
    retry_transport = ScriptedTransport(
        (
            OpenAlexResponse(403, {}, {"message": "forbidden"}),
            OpenAlexResponse(429, {}, {"message": "slow down"}),
            OpenAlexResponse(500, {}, {"message": "server"}),
            _ok(_work_payload("W1")),
        )
    )
    sleeps: list[float] = []
    retry_client = OpenAlexClient(
        api_key="test-key",
        transport=retry_transport,
        max_retries=4,
        sleeper=sleeps.append,
    )

    assert retry_client.get_work("W1").work_id == "W1"
    assert sleeps == [1.0, 2.0, 4.0]

    bad_request_transport = ScriptedTransport(
        (OpenAlexResponse(400, {}, {"message": "bad filter"}),)
    )
    bad_client = OpenAlexClient(api_key="test-key", transport=bad_request_transport)
    with pytest.raises(OpenAlexAPIError, match="HTTP 400"):
        bad_client.search_works("x", limit=1)
    assert len(bad_request_transport.requests) == 1


def _ok(payload: Mapping[str, object]) -> OpenAlexResponse:
    return OpenAlexResponse(200, {}, payload)


def _page(
    works: tuple[Mapping[str, object], ...],
    *,
    next_cursor: str | None,
) -> OpenAlexResponse:
    return OpenAlexResponse(
        200,
        {},
        {
            "meta": {"next_cursor": next_cursor, "per_page": 100, "count": len(works)},
            "results": list(works),
        },
    )


def _work_payload(work_id: str) -> dict[str, object]:
    return {
        "id": f"https://openalex.org/{work_id}",
        "doi": "https://doi.org/10.0000/example",
        "title": f"Title {work_id}",
        "display_name": f"Title {work_id}",
        "publication_year": 2026,
        "cited_by_count": 7,
        "abstract_inverted_index": {"alpha": [0], "beta": [1], "gamma": [2]},
        "referenced_works": ["https://openalex.org/W2"],
        "related_works": ["https://openalex.org/W3"],
        "open_access": {"is_oa": True},
        "authorships": [
            {
                "author": {
                    "display_name": "Ada Lovelace",
                    "id": "https://openalex.org/A1",
                    "orcid": None,
                }
            }
        ],
        "primary_location": {
            "landing_page_url": "https://example.test/work",
            "pdf_url": "https://example.test/work.pdf",
            "is_oa": True,
            "source": {"display_name": "Example Journal"},
        },
        "best_oa_location": None,
    }
