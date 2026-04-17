"""Browser errors."""

# TODO: BrowserError, TimeoutError, ElementNotFoundError


class BrowserError(Exception):
    """Base browser exception."""
    pass


class ElementNotFoundError(BrowserError):
    """Element not found on page."""

    def __init__(self, selector: str):
        self.selector = selector
        super().__init__(f"Element not found: {selector}")
