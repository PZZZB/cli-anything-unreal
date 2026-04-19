"""_parse_value.py — Parse CLI string values into JSON-compatible types.

Remote Control API needs correct JSON types (bool, int, float, object),
not raw strings.  This module converts CLI input like ``"true"``,
``"3.14"``, ``"(1,0,0)"`` into Python values that ``json.dumps()``
serialises correctly for UE's property endpoint.
"""

import json


def parse_property_value(raw: str):
    """Convert a CLI string to the appropriate Python/JSON type.

    Rules (first match wins):
    - ``"true"`` / ``"false"`` (case-insensitive) → ``bool``
    - Valid JSON (number, array, object) → parsed value
    - Otherwise → kept as ``str``

    Examples::

        >>> parse_property_value("true")
        True
        >>> parse_property_value("3.14")
        3.14
        >>> parse_property_value("42")
        42
        >>> parse_property_value('{"R":1,"G":0,"B":0,"A":1}')
        {'R': 1, 'G': 0, 'B': 0, 'A': 1}
        >>> parse_property_value("hello")
        'hello'
    """
    # Bool
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False

    # Try JSON (covers int, float, array, object)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    # Keep as string
    return raw
