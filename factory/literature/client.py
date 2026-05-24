"""Typed OpenAlex clients and response parsing."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from json import JSONDecodeError
from typing import Protocol

from factory.literature.errors import OpenAlexAPIError, OpenAlexAuthError

JsonObject = Mapping[str, object]

_WORK_SELECT_FIELDS = (
    "id",
    "doi",
    "title",
    "display_name",
    "publication_year",
    "cited_by_count",
    "abstract_inverted_index",
    "referenced_works",
    "related_works",
    "open_access",
    "authorships",
    "primary_location",
    "best_oa_location",
    "biblio",
)
_MAX_PER_PAGE = 100
_MAX_OR_FILTER_VALUES = 100


@dataclass(frozen=True, slots=True)
class OpenAlexAuthor:
    """Author metadata needed for local BibTeX synthesis."""

    name: str
    openalex_id: str | None = None
    orcid: str | None = None


@dataclass(frozen=True, slots=True)
class OpenAlexWork:
    """Typed slice of an OpenAlex Work consumed by traversal and PaperStore."""

    work_id: str
    title: str
    abstract: str
    referenced_work_ids: tuple[str, ...]
    related_work_ids: tuple[str, ...]
    is_open_access: bool
    doi: str | None
    citation_count: int
    publication_year: int | None = None
    authors: tuple[OpenAlexAuthor, ...] = ()
    venue: str | None = None
    pdf_url: str | None = None
    landing_page_url: str | None = None

    def to_json_object(self) -> dict[str, object]:
        """Return a stable JSON object for local graph and paper caches."""

        return {
            "work_id": self.work_id,
            "title": self.title,
            "abstract": self.abstract,
            "referenced_work_ids": list(self.referenced_work_ids),
            "related_work_ids": list(self.related_work_ids),
            "is_open_access": self.is_open_access,
            "doi": self.doi,
            "citation_count": self.citation_count,
            "publication_year": self.publication_year,
            "authors": [
                {"name": author.name, "openalex_id": author.openalex_id, "orcid": author.orcid}
                for author in self.authors
            ],
            "venue": self.venue,
            "pdf_url": self.pdf_url,
            "landing_page_url": self.landing_page_url,
        }

    @classmethod
    def from_json_object(cls, payload: JsonObject) -> OpenAlexWork:
        """Load a cached work produced by `to_json_object`."""

        return cls(
            work_id=_required_string(payload, "work_id"),
            title=_required_string(payload, "title"),
            abstract=_required_string(payload, "abstract"),
            referenced_work_ids=_string_tuple(payload.get("referenced_work_ids")),
            related_work_ids=_string_tuple(payload.get("related_work_ids")),
            is_open_access=_required_bool(payload, "is_open_access"),
            doi=_optional_string(payload.get("doi")),
            citation_count=_required_int(payload, "citation_count"),
            publication_year=_optional_int(payload.get("publication_year")),
            authors=_authors_from_cache(payload.get("authors")),
            venue=_optional_string(payload.get("venue")),
            pdf_url=_optional_string(payload.get("pdf_url")),
            landing_page_url=_optional_string(payload.get("landing_page_url")),
        )


@dataclass(frozen=True, slots=True)
class OpenAlexResponse:
    """HTTP response payload returned by an OpenAlex transport."""

    status_code: int
    headers: Mapping[str, str]
    payload: JsonObject


class OpenAlexTransport(Protocol):
    """Small HTTP boundary used by `OpenAlexClient` and tests."""

    def get_json(self, endpoint: str, params: Mapping[str, str]) -> OpenAlexResponse:
        """Return parsed JSON for one OpenAlex API request."""


class OpenAlexClientProtocol(Protocol):
    """Client surface used by traversal, CLI, and tests."""

    def get_work(self, work_id: str) -> OpenAlexWork:
        """Return one typed OpenAlex work."""

    def search_works(
        self,
        query: str,
        filters: Mapping[str, str | int | bool] | None = None,
        *,
        limit: int,
    ) -> tuple[OpenAlexWork, ...]:
        """Search OpenAlex Works and return up to `limit` typed records."""

    def get_backward_references(self, work_id: str) -> tuple[str, ...]:
        """Return OpenAlex IDs cited by `work_id`."""

    def get_forward_citations(
        self,
        work_id: str,
        *,
        limit: int,
        max_pages: int,
    ) -> tuple[str, ...]:
        """Return OpenAlex IDs that cite `work_id`."""

    def batch_get_works(self, work_ids: Sequence[str]) -> tuple[OpenAlexWork, ...]:
        """Batch fetch works by OpenAlex ID."""


class UrllibOpenAlexTransport:
    """OpenAlex HTTPS transport using Python's standard library."""

    def __init__(self, base_url: str = "https://api.openalex.org", timeout_seconds: int = 30):
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def get_json(self, endpoint: str, params: Mapping[str, str]) -> OpenAlexResponse:
        query = urllib.parse.urlencode(params)
        url = f"{self._base_url}{endpoint}?{query}"
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                return OpenAlexResponse(
                    status_code=response.status,
                    headers=dict(response.headers.items()),
                    payload=_decode_json_object(response.read()),
                )
        except urllib.error.HTTPError as exc:
            return OpenAlexResponse(
                status_code=exc.code,
                headers=dict(exc.headers.items()),
                payload=_decode_error_json_object(exc.read()),
            )
        except urllib.error.URLError as exc:
            raise OpenAlexAPIError(f"OpenAlex request failed: {exc.reason}") from exc


class OpenAlexClient:
    """Typed wrapper over the OpenAlex Works API using API-key auth."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: OpenAlexTransport | None = None,
        max_retries: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if "OPENALEX_EMAIL" in os.environ:
            raise OpenAlexAuthError("OPENALEX_EMAIL is obsolete; use OPENALEX_API_KEY")
        resolved_key = api_key or os.environ.get("OPENALEX_API_KEY")
        if not resolved_key:
            raise OpenAlexAuthError("OPENALEX_API_KEY is required for live OpenAlex calls")
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        self._api_key = resolved_key
        self._transport = transport or UrllibOpenAlexTransport()
        self._max_retries = max_retries
        self._sleeper = sleeper

    def get_work(self, work_id: str) -> OpenAlexWork:
        payload = self._request(
            "/works/" + urllib.parse.quote(_short_work_id(work_id), safe=""),
            {"select": _select_fields()},
        )
        return parse_openalex_work(payload)

    def search_works(
        self,
        query: str,
        filters: Mapping[str, str | int | bool] | None = None,
        *,
        limit: int,
    ) -> tuple[OpenAlexWork, ...]:
        if limit < 1:
            return ()
        params: dict[str, str] = {
            "search": query,
            "sort": "relevance_score:desc",
            "select": _select_fields(),
        }
        filter_value = _filter_string(filters or {})
        if filter_value:
            params["filter"] = filter_value
        return self._list_works(params, limit=limit, max_pages=None)

    def get_backward_references(self, work_id: str) -> tuple[str, ...]:
        return self.get_work(work_id).referenced_work_ids

    def get_forward_citations(
        self,
        work_id: str,
        *,
        limit: int,
        max_pages: int,
    ) -> tuple[str, ...]:
        if limit < 1 or max_pages < 1:
            return ()
        works = self._list_works(
            {
                "filter": f"cites:{_short_work_id(work_id)}",
                "sort": "cited_by_count:desc",
                "select": _select_fields(),
            },
            limit=limit,
            max_pages=max_pages,
        )
        return tuple(work.work_id for work in works)

    def batch_get_works(self, work_ids: Sequence[str]) -> tuple[OpenAlexWork, ...]:
        requested_ids = tuple(dict.fromkeys(_short_work_id(work_id) for work_id in work_ids))
        fetched: dict[str, OpenAlexWork] = {}
        for start in range(0, len(requested_ids), _MAX_OR_FILTER_VALUES):
            chunk = requested_ids[start : start + _MAX_OR_FILTER_VALUES]
            works = self._list_works(
                {
                    "filter": "openalex:" + "|".join(chunk),
                    "select": _select_fields(),
                },
                limit=len(chunk),
                max_pages=1,
            )
            fetched.update((work.work_id, work) for work in works)
        return tuple(fetched[work_id] for work_id in requested_ids if work_id in fetched)

    def _list_works(
        self,
        params: Mapping[str, str],
        *,
        limit: int,
        max_pages: int | None,
    ) -> tuple[OpenAlexWork, ...]:
        works: list[OpenAlexWork] = []
        cursor = "*"
        pages_fetched = 0
        while len(works) < limit and (max_pages is None or pages_fetched < max_pages):
            page_params = {
                **params,
                "per_page": str(min(_MAX_PER_PAGE, limit - len(works))),
                "cursor": cursor,
            }
            payload = self._request("/works", page_params)
            works.extend(parse_openalex_work(item) for item in _results(payload))
            pages_fetched += 1
            next_cursor = _next_cursor(payload)
            if next_cursor is None or not _results(payload):
                break
            cursor = next_cursor
        return tuple(works[:limit])

    def _request(self, endpoint: str, params: Mapping[str, str]) -> JsonObject:
        request_params = {**params, "api_key": self._api_key}
        for attempt in range(self._max_retries):
            response = self._transport.get_json(endpoint, request_params)
            if response.status_code == 200:
                return response.payload
            if response.status_code in {400, 404}:
                raise _api_error(response)
            if response.status_code in {403, 429} or response.status_code >= 500:
                if attempt + 1 == self._max_retries:
                    raise _api_error(response)
                self._sleeper(float(2**attempt))
            else:
                raise _api_error(response)
        raise OpenAlexAPIError("OpenAlex request exhausted retry loop")


class InMemoryOpenAlexClient:
    """Deterministic client backed by typed works."""

    def __init__(self, works: Mapping[str, OpenAlexWork]) -> None:
        self._works = {_short_work_id(work_id): work for work_id, work in works.items()}

    def get_work(self, work_id: str) -> OpenAlexWork:
        normalized_id = _short_work_id(work_id)
        work = self._works.get(normalized_id)
        if work is None:
            raise OpenAlexAPIError(f"OpenAlex mock payload missing work: {normalized_id}")
        return work

    def search_works(
        self,
        query: str,
        filters: Mapping[str, str | int | bool] | None = None,
        *,
        limit: int,
    ) -> tuple[OpenAlexWork, ...]:
        if filters and filters.get("open_access.is_oa") is True:
            candidates = tuple(work for work in self._works.values() if work.is_open_access)
        else:
            candidates = tuple(self._works.values())
        query_terms = tuple(term for term in query.lower().split() if term)
        ranked = sorted(
            candidates,
            key=lambda work: (
                -sum(term in f"{work.title} {work.abstract}".lower() for term in query_terms),
                -work.citation_count,
                work.work_id,
            ),
        )
        return tuple(ranked[:limit])

    def get_backward_references(self, work_id: str) -> tuple[str, ...]:
        return self.get_work(work_id).referenced_work_ids

    def get_forward_citations(
        self,
        work_id: str,
        *,
        limit: int,
        max_pages: int,
    ) -> tuple[str, ...]:
        if limit < 1 or max_pages < 1:
            return ()
        target_id = _short_work_id(work_id)
        citing = tuple(
            work.work_id
            for work in sorted(self._works.values(), key=lambda item: item.work_id)
            if target_id in {_short_work_id(item) for item in work.referenced_work_ids}
        )
        return citing[:limit]

    def batch_get_works(self, work_ids: Sequence[str]) -> tuple[OpenAlexWork, ...]:
        return tuple(self.get_work(work_id) for work_id in work_ids)

def parse_openalex_work(payload: JsonObject) -> OpenAlexWork:
    """Parse the selected OpenAlex Work fields into the local typed model."""

    work_id = _short_work_id(_required_string(payload, "id"))
    title = _optional_string(payload.get("title")) or _optional_string(payload.get("display_name"))
    if title is None:
        raise OpenAlexAPIError(f"OpenAlex work {work_id} is missing title/display_name")
    open_access = _object(payload.get("open_access"))
    primary_location = _object(payload.get("primary_location"))
    best_oa_location = _object(payload.get("best_oa_location"))
    selected_location = best_oa_location or primary_location

    return OpenAlexWork(
        work_id=work_id,
        title=title,
        abstract=_decode_abstract(payload.get("abstract_inverted_index")),
        referenced_work_ids=tuple(
            _short_work_id(item) for item in _string_tuple(payload.get("referenced_works"))
        ),
        related_work_ids=tuple(
            _short_work_id(item) for item in _string_tuple(payload.get("related_works"))
        ),
        is_open_access=_open_access_flag(open_access, selected_location),
        doi=_normalize_doi(_optional_string(payload.get("doi"))),
        citation_count=_required_int(payload, "cited_by_count"),
        publication_year=_optional_int(payload.get("publication_year")),
        authors=_authors_from_openalex(payload.get("authorships")),
        venue=_venue(selected_location),
        pdf_url=_optional_string(selected_location.get("pdf_url")),
        landing_page_url=_optional_string(selected_location.get("landing_page_url")),
    )


def with_updated_edges(
    work: OpenAlexWork,
    referenced_work_ids: Sequence[str],
    related_work_ids: Sequence[str],
) -> OpenAlexWork:
    """Return `work` with normalized citation/related-work edges."""

    return replace(
        work,
        referenced_work_ids=tuple(
            dict.fromkeys(_short_work_id(item) for item in referenced_work_ids)
        ),
        related_work_ids=tuple(dict.fromkeys(_short_work_id(item) for item in related_work_ids)),
    )


def _request_message(payload: JsonObject) -> str:
    message = payload.get("message")
    if isinstance(message, str) and message:
        return message
    error = payload.get("error")
    if isinstance(error, str) and error:
        return error
    return "OpenAlex API request failed"


def _api_error(response: OpenAlexResponse) -> OpenAlexAPIError:
    return OpenAlexAPIError(
        f"OpenAlex HTTP {response.status_code}: {_request_message(response.payload)}"
    )


def _decode_json_object(raw: bytes) -> JsonObject:
    try:
        decoded: object = json.loads(raw.decode("utf-8"))
    except JSONDecodeError as exc:
        raise OpenAlexAPIError("OpenAlex returned malformed JSON") from exc
    if not isinstance(decoded, dict):
        raise OpenAlexAPIError("OpenAlex returned non-object JSON")
    return decoded


def _decode_error_json_object(raw: bytes) -> JsonObject:
    try:
        return _decode_json_object(raw)
    except OpenAlexAPIError:
        return {"message": "OpenAlex returned non-JSON error response"}


def _select_fields() -> str:
    return ",".join(_WORK_SELECT_FIELDS)


def _filter_string(filters: Mapping[str, str | int | bool]) -> str:
    parts = []
    for key, value in sorted(filters.items()):
        encoded_value = ("true" if value else "false") if isinstance(value, bool) else str(value)
        parts.append(f"{key}:{encoded_value}")
    return ",".join(parts)


def _results(payload: JsonObject) -> tuple[JsonObject, ...]:
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise OpenAlexAPIError("OpenAlex list response missing results")
    results: list[JsonObject] = []
    for item in raw_results:
        if not isinstance(item, dict):
            raise OpenAlexAPIError("OpenAlex result entry must be an object")
        results.append(item)
    return tuple(results)


def _next_cursor(payload: JsonObject) -> str | None:
    meta = _object(payload.get("meta"))
    return _optional_string(meta.get("next_cursor"))


def _decode_abstract(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, dict):
        raise OpenAlexAPIError("abstract_inverted_index must be an object when present")
    positions: list[tuple[int, str]] = []
    for raw_word, raw_indexes in value.items():
        if not isinstance(raw_word, str):
            raise OpenAlexAPIError("abstract_inverted_index keys must be strings")
        if not isinstance(raw_indexes, list):
            raise OpenAlexAPIError("abstract_inverted_index values must be lists")
        for raw_index in raw_indexes:
            if not isinstance(raw_index, int) or isinstance(raw_index, bool):
                raise OpenAlexAPIError("abstract_inverted_index positions must be integers")
            positions.append((raw_index, raw_word))
    return " ".join(word for _, word in sorted(positions))


def _authors_from_openalex(value: object) -> tuple[OpenAlexAuthor, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise OpenAlexAPIError("authorships must be a list")
    authors: list[OpenAlexAuthor] = []
    for item in value:
        item_obj = _object(item)
        author = _object(item_obj.get("author"))
        name = _optional_string(author.get("display_name"))
        if name is not None:
            authors.append(
                OpenAlexAuthor(
                    name=name,
                    openalex_id=_optional_string(author.get("id")),
                    orcid=_optional_string(author.get("orcid")),
                )
            )
    return tuple(authors)


def _authors_from_cache(value: object) -> tuple[OpenAlexAuthor, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise OpenAlexAPIError("cached authors must be a list")
    authors: list[OpenAlexAuthor] = []
    for item in value:
        item_obj = _object(item)
        authors.append(
            OpenAlexAuthor(
                name=_required_string(item_obj, "name"),
                openalex_id=_optional_string(item_obj.get("openalex_id")),
                orcid=_optional_string(item_obj.get("orcid")),
            )
        )
    return tuple(authors)


def _venue(location: JsonObject) -> str | None:
    source = _object(location.get("source"))
    return _optional_string(source.get("display_name"))


def _open_access_flag(open_access: JsonObject, selected_location: JsonObject) -> bool:
    open_access_value = open_access.get("is_oa")
    if isinstance(open_access_value, bool):
        return open_access_value

    location_value = selected_location.get("is_oa")
    if isinstance(location_value, bool):
        return location_value

    raise OpenAlexAPIError("OpenAlex response missing open_access.is_oa")


def _short_work_id(work_id: str) -> str:
    stripped = work_id.rstrip("/")
    if "/" in stripped:
        stripped = stripped.rsplit("/", 1)[-1]
    if not stripped:
        raise OpenAlexAPIError("OpenAlex work ID must be non-empty")
    return stripped


def _normalize_doi(doi: str | None) -> str | None:
    if doi is None:
        return None
    lowered = doi.lower()
    if lowered.startswith("https://doi.org/"):
        return doi[len("https://doi.org/") :]
    return doi


def _object(value: object) -> JsonObject:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise OpenAlexAPIError("expected JSON object")
    return value


def _required_string(payload: JsonObject, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or value == "":
        raise OpenAlexAPIError(f"field {key} must be a non-empty string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise OpenAlexAPIError("expected optional string")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise OpenAlexAPIError("expected string list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise OpenAlexAPIError("expected list of strings")
        result.append(item)
    return tuple(result)


def _required_bool(payload: JsonObject, key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise OpenAlexAPIError(f"field {key} must be a bool")
    return value


def _required_int(payload: JsonObject, key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise OpenAlexAPIError(f"field {key} must be an integer")
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise OpenAlexAPIError("expected optional integer")
    return value
