"""Redmine REST client implementing the ``IssueSource`` port."""

import logging
from collections.abc import Iterator
from itertools import islice
from typing import Any
from urllib.parse import urlencode

from ..config import RedmineCfg
from ..domain.models import Attachment, Journal, Relation, Ticket
from ..errors import SourceError, TransportError
from ..ports import Transport

log = logging.getLogger(__name__)

# Redmine relation type -> (label seen from the stored "issue_id" side, label seen from "issue_to_id" side)
_RELATION_LABELS = {
    "relates": ("relates to", "relates to"),
    "blocks": ("blocks", "blocked by"),
    "blocked": ("blocked by", "blocks"),
    "precedes": ("precedes", "follows"),
    "follows": ("follows", "precedes"),
    "duplicates": ("duplicates", "duplicated by"),
    "duplicated": ("duplicated by", "duplicates"),
    "copied_to": ("copied to", "copied from"),
    "copied_from": ("copied from", "copied to"),
}
_INCLUDES = "journals,relations,children,attachments,changesets"


def _name(obj: Any) -> str:
    """``name`` of a Redmine reference object such as ``{"id": 1, "name": "New"}``."""
    return str(obj.get("name", "")) if isinstance(obj, dict) else ""


class RedmineClient:
    """Read-only Redmine client. Retries live in the injected transport, not here."""

    def __init__(self, cfg: RedmineCfg, transport: Transport) -> None:
        self._cfg = cfg
        self._transport = transport
        # Lookup tables are fetched lazily. They are memoised on success and on permanent failure (4xx),
        # but a transient failure is retried on the next ticket instead of poisoning the whole run.
        self._statuses: dict[int, tuple[str, bool]] | None = None
        self._priorities: dict[int, str] | None = None

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        url = f"{self._cfg.url}{path}" + (f"?{urlencode(params)}" if params else "")
        try:
            data = self._transport.request_json(
                url, headers={"X-Redmine-API-Key": self._cfg.api_key}, timeout=self._cfg.timeout
            )
        except TransportError as exc:
            raise SourceError(f"{path}: {exc}", exc.status) from exc
        if not isinstance(data, dict):
            raise SourceError(f"{path}: unexpected response (not a JSON object)")
        return data

    def _paginate(self, path: str, key: str, **params: Any) -> Iterator[dict[str, Any]]:
        """Yield all items of a list endpoint, following offset/limit pagination lazily."""
        offset = 0
        while True:
            page = self._get(path, offset=offset, limit=self._cfg.page_size, **params)
            items = page.get(key)
            if not isinstance(items, list) or not items:
                return
            yield from items
            offset += len(items)
            if offset >= page.get("total_count", 0):
                return

    def _status_table(self) -> dict[int, tuple[str, bool]]:
        if self._statuses is None:
            try:
                rows = self._get("/issue_statuses.json")["issue_statuses"]
                self._statuses = {s["id"]: (s["name"], bool(s.get("is_closed"))) for s in rows}
            except (SourceError, KeyError, TypeError) as exc:
                log.warning("status lookup unavailable (%s): open/closed state will be unknown", exc)
                if isinstance(exc, SourceError) and not 400 <= exc.status < 500:
                    return {}  # transient: try again with the next ticket
                self._statuses = {}
        return self._statuses

    def _priority_table(self) -> dict[int, str]:
        if self._priorities is None:
            try:
                rows = self._get("/enumerations/issue_priorities.json")["issue_priorities"]
                self._priorities = {p["id"]: p["name"] for p in rows}
            except (SourceError, KeyError, TypeError) as exc:
                log.warning("priority lookup unavailable (%s): priority ids stay raw in change history", exc)
                if isinstance(exc, SourceError) and not 400 <= exc.status < 500:
                    return {}
                self._priorities = {}
        return self._priorities

    def search(self, query: str, project: str | None, status: str, limit: int) -> list[Ticket]:
        """Find tickets by numeric id or subject substring (lightweight: no journals).

        ``status`` is ``open``, ``closed`` or ``all``.
        """
        params: dict[str, Any] = {"status_id": "*" if status == "all" else status, "sort": "updated_on:desc"}
        if query.isdigit():
            params = {"issue_id": query, "status_id": "*"}
        elif query:
            params["subject"] = f"~{query}"
        if project:
            params["project_id"] = project
        return [self._parse(item) for item in islice(self._paginate("/issues.json", "issues", **params), limit)]

    def get_issue(self, issue_id: int) -> Ticket:
        """Fetch one ticket with its full conversation, relations, children, attachment names and commits."""
        data = self._get(f"/issues/{issue_id}.json", include=_INCLUDES)
        if not isinstance(data.get("issue"), dict):
            raise SourceError(f"/issues/{issue_id}.json: response has no 'issue' object")
        return self._parse(data["issue"])

    def _format_change(self, detail: dict[str, Any], custom_field_names: dict[int, str]) -> str:
        """One journal detail as ``field: old → new`` with ids resolved to names where possible."""
        prop, name = detail.get("property"), str(detail.get("name"))
        old, new = detail.get("old_value"), detail.get("new_value")
        if prop == "attachment":
            return f"attachment: {new or old}"
        if prop == "cf":
            name = custom_field_names.get(int(name), f"custom field {name}") if name.isdigit() else name
        elif name == "status_id":
            statuses = self._status_table()
            old, new = (statuses.get(int(v), (v,))[0] if v else v for v in (old, new))
        elif name == "priority_id":
            priorities = self._priority_table()
            old, new = (priorities.get(int(v), v) if v else v for v in (old, new))
        return f"{name}: {old or '∅'} → {new or '∅'}"

    def _parse(self, issue: dict[str, Any]) -> Ticket:
        """Convert a Redmine issue object into a Ticket; tolerant of missing optional fields."""
        try:
            issue_id = int(issue["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceError("response contains an issue without a valid id") from exc

        custom_field_names = {c["id"]: c["name"] for c in issue.get("custom_fields", []) if "id" in c}
        relations = []
        for rel in issue.get("relations", []):
            label_from, label_to = _RELATION_LABELS.get(rel["relation_type"], (rel["relation_type"],) * 2)
            if rel["issue_id"] == issue_id:
                relations.append(Relation(rel["issue_to_id"], label_from))
            else:
                relations.append(Relation(rel["issue_id"], label_to))

        journals = []
        for j in sorted(issue.get("journals", []), key=lambda j: (j.get("created_on", ""), j["id"])):
            changes = tuple(self._format_change(d, custom_field_names) for d in j.get("details", []))
            notes = (j.get("notes") or "").strip()
            if notes or changes:  # drop empty entries (e.g. changes to fields we cannot show)
                journals.append(Journal(j["id"], _name(j.get("user")), j.get("created_on", ""), notes, changes))

        status_id = (issue.get("status") or {}).get("id")
        status_known = status_id in self._status_table()
        custom_fields = {}
        for c in issue.get("custom_fields", []):
            value = c.get("value")
            if value not in (None, "", []):
                custom_fields[c["name"]] = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
        return Ticket(
            id=issue_id,
            subject=issue.get("subject", ""),
            description=(issue.get("description") or "").strip(),
            tracker=_name(issue.get("tracker")),
            status=_name(issue.get("status")),
            closed=self._status_table()[status_id][1] if status_known else None,
            priority=_name(issue.get("priority")),
            author=_name(issue.get("author")),
            assignee=_name(issue.get("assigned_to")),
            project=_name(issue.get("project")),
            created_on=issue.get("created_on", ""),
            updated_on=issue.get("updated_on", ""),
            url=f"{self._cfg.url}/issues/{issue_id}",
            custom_fields=custom_fields,
            journals=tuple(journals),
            parent_id=(issue.get("parent") or {}).get("id"),
            children=tuple(c["id"] for c in issue.get("children", [])),
            relations=tuple(relations),
            attachments=tuple(
                Attachment(a["filename"], a.get("content_url", "")) for a in issue.get("attachments", [])
            ),
            commits=tuple(
                (c["revision"], (c.get("comments") or "").strip()[:300]) for c in issue.get("changesets", [])
            ),
        )
