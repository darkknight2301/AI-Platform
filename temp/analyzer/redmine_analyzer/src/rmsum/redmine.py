"""Redmine REST client: issues with journals/relations/children/attachments/changesets."""

import logging
import time
from collections.abc import Iterator
from functools import cached_property
from itertools import islice
from urllib.parse import urlencode

from .config import RedmineCfg
from .httpjson import Fetch, HttpError, request_json
from .models import Attachment, Journal, Ticket

log = logging.getLogger(__name__)

# Redmine relation type -> (label from the stored side, label from the other side)
_REL = {
    "relates": ("relates to", "relates to"), "blocks": ("blocks", "blocked by"),
    "blocked": ("blocked by", "blocks"), "precedes": ("precedes", "follows"),
    "follows": ("follows", "precedes"), "duplicates": ("duplicates", "duplicated by"),
    "duplicated": ("duplicated by", "duplicates"), "copied_to": ("copied to", "copied from"),
    "copied_from": ("copied from", "copied to"),
}


class RedmineError(Exception):
    """A Redmine request failed permanently (4xx, or 5xx/network after retries)."""


class RedmineClient:
    """Thin read-only Redmine client with retries and transparent pagination."""

    def __init__(self, cfg: RedmineCfg, fetch: Fetch = request_json):
        self._cfg = cfg
        self._fetch = fetch

    def _get(self, path: str, **params) -> dict:
        """GET ``path`` with retries on 5xx/network errors; 4xx fails immediately."""
        url = f"{self._cfg.url}{path}" + (f"?{urlencode(params)}" if params else "")
        last: HttpError | None = None
        for attempt in range(3):
            try:
                return self._fetch(url, headers={"X-Redmine-API-Key": self._cfg.api_key},
                                   timeout=self._cfg.timeout, verify_ssl=self._cfg.verify_ssl)
            except HttpError as e:
                if 400 <= e.status < 500:
                    raise RedmineError(f"{path}: {e}") from e
                last = e
                log.warning("Redmine %s failed (%s), attempt %d/3", path, e, attempt + 1)
                if attempt < 2:
                    time.sleep(0.5 * 2 ** attempt)
        raise RedmineError(f"{path}: {last}") from last

    def _paginate(self, path: str, key: str, **params) -> Iterator[dict]:
        """Yield all items of a list endpoint, following offset/limit pagination lazily."""
        offset = 0
        while True:
            page = self._get(path, offset=offset, limit=self._cfg.page_size, **params)
            items = page[key]
            yield from items
            offset += len(items)
            if not items or offset >= page.get("total_count", 0):
                return

    @cached_property
    def _statuses(self) -> dict[int, tuple[str, bool]]:
        """Status id -> (name, is_closed); empty if the endpoint is unavailable."""
        try:
            return {s["id"]: (s["name"], s.get("is_closed", False))
                    for s in self._get("/issue_statuses.json")["issue_statuses"]}
        except RedmineError:
            return {}

    @cached_property
    def _priorities(self) -> dict[int, str]:
        """Priority id -> name; empty if the endpoint is unavailable."""
        try:
            return {p["id"]: p["name"]
                    for p in self._get("/enumerations/issue_priorities.json")["issue_priorities"]}
        except RedmineError:
            return {}

    def search(self, query: str, project: str | None = None, status: str = "open",
               limit: int = 20) -> list[Ticket]:
        """Find tickets by numeric id or subject substring (lightweight, no journals).

        Args:
            status: ``open``, ``closed`` or ``all``.
        """
        params = {"status_id": "*" if status == "all" else status, "sort": "updated_on:desc"}
        if query.isdigit():
            params = {"issue_id": query, "status_id": "*"}
        elif query:
            params["subject"] = f"~{query}"
        if project:
            params["project_id"] = project
        return [self._parse(i) for i in islice(self._paginate("/issues.json", "issues", **params), limit)]

    def get_issue(self, issue_id: int) -> Ticket:
        """Fetch one ticket with its full conversation, relations, children and attachments."""
        data = self._get(f"/issues/{issue_id}.json",
                         include="journals,relations,children,attachments,changesets")
        return self._parse(data["issue"])

    def _change(self, d: dict, cf_names: dict[int, str]) -> str:
        """Format one journal detail as ``field: old -> new`` with names resolved where possible."""
        prop, name, old, new = d.get("property"), str(d.get("name")), d.get("old_value"), d.get("new_value")
        if prop == "attachment":
            return f"attachment: {new or old}"
        if prop == "cf":
            name = cf_names.get(int(name), f"custom field {name}") if name.isdigit() else name
        elif name == "status_id":
            old, new = (self._statuses.get(int(v), (v,))[0] if v else v for v in (old, new))
        elif name == "priority_id":
            old, new = (self._priorities.get(int(v), v) if v else v for v in (old, new))
        return f"{name}: {old or '∅'} → {new or '∅'}"

    def _parse(self, i: dict) -> Ticket:
        """Convert a Redmine issue JSON object into a Ticket."""
        name = lambda k: (i.get(k) or {}).get("name", "")  # noqa: E731
        cf_names = {c["id"]: c["name"] for c in i.get("custom_fields", [])}
        relations = []
        for r in i.get("relations", []):
            fwd, inv = _REL.get(r["relation_type"], (r["relation_type"],) * 2)
            relations.append((r["issue_to_id"], fwd) if r["issue_id"] == i["id"] else (r["issue_id"], inv))
        journals = [
            Journal(j["id"], (j.get("user") or {}).get("name", ""), j.get("created_on", ""),
                    (j.get("notes") or "").strip(), [self._change(d, cf_names) for d in j.get("details", [])])
            for j in sorted(i.get("journals", []), key=lambda j: (j.get("created_on", ""), j["id"]))
        ]
        status_id = (i.get("status") or {}).get("id")
        return Ticket(
            id=i["id"], subject=i.get("subject", ""), description=(i.get("description") or "").strip(),
            tracker=name("tracker"), status=name("status"),
            closed=self._statuses.get(status_id, ("", False))[1],
            priority=name("priority"), author=name("author"), assignee=name("assigned_to"),
            project=name("project"), created_on=i.get("created_on", ""), updated_on=i.get("updated_on", ""),
            url=f"{self._cfg.url}/issues/{i['id']}",
            custom_fields={c["name"]: ", ".join(map(str, v)) if isinstance(v := c.get("value"), list) else str(v)
                           for c in i.get("custom_fields", []) if c.get("value") not in (None, "", [])},
            journals=[j for j in journals if j.notes or j.changes],
            parent_id=(i.get("parent") or {}).get("id"),
            children=[c["id"] for c in i.get("children", [])],
            relations=relations,
            attachments=[Attachment(a["filename"], a.get("content_url", "")) for a in i.get("attachments", [])],
            commits=[(c["revision"], (c.get("comments") or "").strip()[:300]) for c in i.get("changesets", [])],
        )
