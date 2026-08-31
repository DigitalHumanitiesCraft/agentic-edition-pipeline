"""Edition-convention markers of the transcription prompt, in one place.

pipeline/prompts/transcription.md instructs the vision model to mark five
things in the page text: an uncertain reading as [?], an illegible passage as
[...] or [... ~N chars], struck-through text as ~~text~~ and an editorial
insertion as {text}. Every consumer that counts, hides or resolves these
markers reads their syntax from here, so prompt and pipeline cannot drift
apart, and a marker never reads as transcription noise (step 4).

strip_markers removes a marker together with the text it wraps and is the
right choice before a scan for artifacts. resolve_markers produces the
reading text instead: the insertion stays, the struck-through text goes, the
two bracket markers vanish.
"""

from __future__ import annotations

import re

UNCERTAIN = r"\[\?\]"
ILLEGIBLE = r"\[\.\.\.(?:\s*~\s*\d+\s*chars?)?\]"
STRIKETHROUGH = r"~~(.*?)~~"
INSERTION = r"\{(.*?)\}"

ALL_MARKERS = (UNCERTAIN, ILLEGIBLE, STRIKETHROUGH, INSERTION)

_STRIP_RE = re.compile("|".join(ALL_MARKERS))


def strip_markers(text: str) -> str:
    """Remove every convention marker, including the text a marker wraps."""
    if not text:
        return ""
    return _STRIP_RE.sub("", text)


def resolve_markers(text: str) -> str:
    """Resolve the markers to the reading text of the page.

    An insertion is text the writer added and stays; struck-through text is
    text the writer removed and goes; the uncertainty and illegibility
    brackets carry no text of their own.
    """
    if not text:
        return ""
    text = re.sub(STRIKETHROUGH, "", text)
    text = re.sub(INSERTION, r"\1", text)
    text = re.sub(UNCERTAIN, "", text)
    return re.sub(ILLEGIBLE, "", text)
