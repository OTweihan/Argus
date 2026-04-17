"""LLM response parser (JSON extraction, validation)."""


def extract_json(text: str) -> dict:
    """Extract JSON from LLM response text.

    Handles cases where the model wraps JSON in markdown code blocks.

    Args:
        text: Raw LLM response text.

    Returns:
        Parsed JSON dict.

    Raises:
        ValueError: If no valid JSON found.
    """
    # TODO: Extract JSON from code blocks, validate, return dict
    raise NotImplementedError("extract_json() not yet implemented")
