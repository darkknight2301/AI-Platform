"""Pure screen-geometry maths (no Qt) so multi-monitor logic is unit-testable."""
from dataclasses import dataclass
from typing import NamedTuple, Sequence, Tuple

POSITIONS = ("bottom_right", "bottom_left", "bottom_center")


class Rect(NamedTuple):
    x: int
    y: int
    w: int
    h: int

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


@dataclass(frozen=True)
class MotionPlan:
    start: Tuple[int, int]   # off-screen point the character walks in from / leaves to
    end: Tuple[int, int]     # resting position
    side: str                # "left" | "right" | "bottom"


def plan_motion(screen: Rect, available: Rect, others: Sequence[Rect],
                size: Tuple[int, int], position: str = "bottom_right",
                margin: int = 24) -> MotionPlan:
    """Work out where the overlay rests and which edge it enters/leaves through.

    ``screen`` is the full monitor rect, ``available`` excludes the taskbar and
    ``others`` are the other monitors. An entry edge that touches another monitor
    is avoided so the character does not visibly walk across a neighbouring screen.
    """
    w, h = size
    if position == "bottom_left":
        tx = available.x + margin
    elif position == "bottom_center":
        tx = available.x + (available.w - w) // 2
    else:
        tx = available.x + available.w - w - margin
    tx = max(available.x, tx)
    ty = max(available.y, available.y + available.h - h - margin)

    mid_y = ty + h // 2
    candidates = {
        "right": ((screen.x + screen.w, ty), (screen.x + screen.w + 1, mid_y)),
        "left": ((screen.x - w, ty), (screen.x - 1, mid_y)),
        "bottom": ((tx, screen.y + screen.h), (tx + w // 2, screen.y + screen.h + 1)),
    }
    order = ("left", "right", "bottom") if position == "bottom_left" else ("right", "left", "bottom")
    chosen = order[0]
    for side in order:
        probe = candidates[side][1]
        if not any(o.contains(*probe) for o in others):
            chosen = side
            break
    return MotionPlan(start=candidates[chosen][0], end=(tx, ty), side=chosen)
