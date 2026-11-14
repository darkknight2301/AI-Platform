"""Breadth-first traversal of parent, child, sub-task and related tickets."""

import logging
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field

from .extract import extract_facts
from .models import Ticket
from .redmine import RedmineClient, RedmineError

log = logging.getLogger(__name__)


@dataclass
class TicketGraph:
    """Tickets reachable from ``root_id``, in discovery order (root first).

    ``via`` says how each ticket was reached; ``skipped`` lists tickets seen but not
    fetched (depth/size limit or fetch error) so nothing disappears silently.
    """
    root_id: int
    tickets: dict[int, Ticket] = field(default_factory=dict)
    via: dict[int, str] = field(default_factory=dict)
    edges: list[tuple[int, str, int]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _neighbours(t: Ticket, follow_text_refs: bool, redmine_url: str) -> Iterator[tuple[int, str]]:
    """Yield ``(other_id, label)`` links from ``t``: parent, children, relations, text mentions."""
    if t.parent_id:
        yield t.parent_id, "child of"
    for c in t.children:
        yield c, "parent of"
    yield from t.relations
    if follow_text_refs:
        for f in extract_facts([t], redmine_url):
            if f.kind == "ticket":
                yield int(f.value[1:]), "mentions"


def build_graph(client: RedmineClient, root_id: int, *, max_depth: int = 2, max_tickets: int = 25,
                follow_text_refs: bool = False, redmine_url: str = "") -> TicketGraph:
    """Fetch ``root_id`` and, breadth-first, its related tickets.

    A visited set prevents loops and duplicate fetches. Failure to fetch the root raises
    :class:`RedmineError`; failures on related tickets are recorded in ``skipped``.
    """
    root = client.get_issue(root_id)
    g = TicketGraph(root_id, {root_id: root}, {root_id: "root"})
    seen = {root_id}
    linked: set[frozenset[int]] = set()
    queue = deque([(root, 0)])
    while queue:
        t, depth = queue.popleft()
        for dst, label in _neighbours(t, follow_text_refs, redmine_url):
            if dst == t.id:
                continue
            if (pair := frozenset((t.id, dst))) not in linked:  # parent/child are seen from both ends
                linked.add(pair)
                g.edges.append((t.id, label, dst))
            if dst in seen:
                continue
            seen.add(dst)
            edge = f"#{t.id} {label} #{dst}"
            if depth + 1 > max_depth:
                g.skipped.append(f"#{dst}: beyond max depth {max_depth} ({edge})")
            elif len(g.tickets) >= max_tickets:
                g.skipped.append(f"#{dst}: ticket limit {max_tickets} reached ({edge})")
            else:
                try:
                    g.tickets[dst] = client.get_issue(dst)
                except RedmineError as e:
                    log.warning("cannot fetch #%d: %s", dst, e)
                    g.skipped.append(f"#{dst}: fetch failed ({e}) ({edge})")
                    continue
                g.via[dst] = edge
                queue.append((g.tickets[dst], depth + 1))
    return g
