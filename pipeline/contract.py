"""Runtime checks for the pipeline data contract (knowledge/08_DATA_CONTRACT.md).

The contract binds steps 3 to 6: object_id and pages at the top level, a
provenance block under _meta, and per page an integer page number from 1 and
a transcription string. These functions are the single source for those field
rules. Step 3 gates the model answer with response_violations before writing,
and the contract tests check finished files with file_violations, so a rule
change lands in one place instead of two.

Both functions return a list of human-readable problems and an empty list
when the input conforms; they never raise, so a caller can decide whether a
violation is a skipped item or a hard stop.
"""
from __future__ import annotations

REQUIRED_TOP_LEVEL = ("object_id", "pages")
REQUIRED_META = ("script", "timestamp")


def page_violations(pages: object) -> list[str]:
    """Check the page array against the contract's mandatory page fields."""
    if not isinstance(pages, list):
        return ["pages is not a list"]

    problems: list[str] = []
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            problems.append(f"pages[{index}] is not an object")
            continue
        number = page.get("page")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            problems.append(f"pages[{index}] has no page number from 1")
        if not isinstance(page.get("transcription"), str):
            problems.append(f"pages[{index}] has no transcription string")
    return problems


def response_violations(response: object) -> list[str]:
    """Check a model answer before step 3 writes it to disk.

    An answer without a usable pages/transcription structure is an error of
    the object, because writing it would produce a file that claims an empty
    but reviewed transcription.
    """
    if not isinstance(response, dict):
        return ["model response is not a JSON object"]
    pages = response.get("pages")
    if not isinstance(pages, list):
        return ["model response carries no pages array"]
    if not pages:
        return ["model response carries an empty pages array"]
    return page_violations(pages)


def file_violations(data: object) -> list[str]:
    """Check a complete transcription or validation file against the contract."""
    if not isinstance(data, dict):
        return ["file content is not a JSON object"]

    problems = [f"missing top-level key: {key}"
                for key in REQUIRED_TOP_LEVEL if key not in data]

    meta = data.get("_meta")
    if not isinstance(meta, dict):
        problems.append("missing provenance block: _meta")
    else:
        problems += [f"_meta is missing {key}" for key in REQUIRED_META if not meta.get(key)]

    if "object_id" in data and not (isinstance(data["object_id"], str) and data["object_id"]):
        problems.append("object_id is not a non-empty string")

    if "pages" in data:
        problems += page_violations(data["pages"])

    return problems
