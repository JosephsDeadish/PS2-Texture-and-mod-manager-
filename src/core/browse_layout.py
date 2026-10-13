"""Layout helpers for the browse catalogue grid."""


def calculate_catalogue_columns(viewport_width: int) -> int:
    """Return a responsive grid column count for the browse catalogue."""
    if viewport_width <= 0:
        return 3
    return max(1, min(4, viewport_width // 274))

