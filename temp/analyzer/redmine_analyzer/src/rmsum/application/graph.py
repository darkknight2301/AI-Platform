"""Breadth-first traversal of parent, child, sub-task and related tickets."""

import logging
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass

from ..domain.extraction import extract_facts
from ..domain.models import FactKind, SkippedTicket, Ticket
from ..errors import SourceError
from ..ports import IssueSource

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TicketGraph:
    """Tickets reachable from ``root_id`` in discovery order (root first).

    ``via`` says how each ticket was reached; ``skipped`` lists tickets that were seen but not
    fetched (depth/size limit or fetch error), so nothing disappears silently.
    """

    root_id: int
    tickets: dict[int, Ticket]
    via: dict[int, str]
    edges: tuple[tuple[int, str, int], ...]
    skipped: tuple[SkippedTicket, ...]
    warnings: tuple[str, ...]


class TicketGraphLoader:
    """Loads a ticket and the tickets related to it, with loop protection and hard limits."""

    def __init__(
        self,
        source: IssueSource,
        *,
        max_depth: int,
        max_tickets: int,
        follow_text_refs: bool,
        redmine_url: str,
    ) -> None:
        self._source = source
        self._max_depth = max_depth
        self._max_tickets = max_tickets
        self._follow_text_refs = follow_text_refs
        self._redmine_url = redmine_url

    def _neighbours(self, ticket: Ticket) -> Iterator[tuple[int, str]]:
        """Yield ``(other_id, label)`` for the parent, children, relations and (optionally) text mentions."""
        if ticket.parent_id:
            yield ticket.parent_id, "child of"
        for child in ticket.children:
            yield child, "parent of"
        for relation in ticket.relations:
            yield relation.other_id, relation.label
        if self._follow_text_refs:
            for fact in extract_facts([ticket], self._redmine_url):
                if fact.kind is FactKind.TICKET:
                    yield int(fact.value[1:]), "mentions"

    def load(self, root_id: int) -> TicketGraph:
        """Fetch ``root_id`` and, breadth-first, its related tickets.

        A visited set prevents loops and duplicate fetches. Failure to fetch the root raises
        :class:`SourceError`; failures on related tickets are recorded in ``skipped``.
        """
        root = self._source.get_issue(root_id)
        tickets = {root_id: root}
        via = {root_id: "root"}
        edges: list[tuple[int, str, int]] = []
        skipped: list[SkippedTicket] = []
        seen = {root_id}
        linked: set[frozenset[int]] = set()
        queue = deque([(root, 0)])
        while queue:
            ticket, depth = queue.popleft()
            for other_id, label in self._neighbours(ticket):
                if other_id == ticket.id:
                    continue
                pair = frozenset((ticket.id, other_id))
                if pair not in linked:  # parent/child links are visible from both ends; record once
                    linked.add(pair)
                    edges.append((ticket.id, label, other_id))
                if other_id in seen:
                    continue
                seen.add(other_id)
                edge = f"#{ticket.id} {label} #{other_id}"
                if depth + 1 > self._max_depth:
                    skipped.append(SkippedTicket(other_id, f"beyond max depth {self._max_depth}", edge))
                elif len(tickets) >= self._max_tickets:
                    skipped.append(SkippedTicket(other_id, f"ticket limit {self._max_tickets} reached", edge))
                else:
                    try:
                        tickets[other_id] = self._source.get_issue(other_id)
                    except SourceError as exc:
                        log.warning("cannot fetch #%d: %s", other_id, exc)
                        skipped.append(SkippedTicket(other_id, f"fetch failed ({exc})", edge))
                        continue
                    via[other_id] = edge
                    queue.append((tickets[other_id], depth + 1))

        warnings = []
        if any(t.closed is None for t in tickets.values()):
            warnings.append("Open/closed state of tickets is unknown because Redmine's status list was unavailable")
        return TicketGraph(root_id, tickets, via, tuple(edges), tuple(skipped), tuple(warnings))
