from dataclasses import dataclass


@dataclass(slots=True)
class SquareBounds:
    left: int
    right: int
    top: int
    bot: int
    h: int

    @classmethod
    def from_squares(cls, squares: list[tuple]) -> "SquareBounds":
        left = min(s[0] for s in squares)
        right = max(s[0] + s[2] for s in squares)
        top = min(s[1] for s in squares)
        bot = max(s[1] + s[3] for s in squares)
        return cls(left, right, top, bot, bot - top)


def icon_region(bounds: SquareBounds, fh: int) -> tuple[int, int, int, int]:
    """Region below squares for space/a-d icon detection."""
    return (bounds.left, bounds.bot, bounds.right, fh)


def bobber_region(bounds: SquareBounds, fw: int, fh: int) -> tuple[int, int, int, int]:
    """Region to the right of squares for bobber template match."""
    return (bounds.right, max(0, bounds.top - bounds.h * 2),
            min(fw, bounds.right + bounds.h * 6), min(fh, bounds.bot + bounds.h * 2))


def take_region(fw: int, fh: int) -> tuple[int, int, int, int]:
    """Center of screen for take dialog detection."""
    return (fw // 5, fh // 4, fw * 4 // 5, fh * 3 // 4)


def bar_search_region(bounds: SquareBounds) -> tuple[int, int, int, int]:
    """Region above squares for slider bar detection (1 square height up)."""
    y1 = max(0, bounds.top - bounds.h)
    return (bounds.left, y1, bounds.right, bounds.top)
