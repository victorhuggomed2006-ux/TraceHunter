"""Tests for the CLI catalog."""

from tracehunter.catalog import DEFAULT_CATALOG, Catalog, CliTool, Confidence


def test_names_are_unique() -> None:
    names = [t.name.lower() for t in DEFAULT_CATALOG.tools]
    assert len(names) == len(set(names))


def test_unknown_tools_have_no_path_and_known_have_one() -> None:
    for tool in DEFAULT_CATALOG.tools:
        if tool.confidence is Confidence.UNKNOWN:
            assert not tool.has_path, tool.name
        else:
            assert tool.has_path, tool.name


def test_find_is_case_insensitive() -> None:
    tool = DEFAULT_CATALOG.find("claude code")
    assert tool is not None
    assert tool.vendor == "Anthropic"
    assert DEFAULT_CATALOG.find("nonexistent") is None


def test_only_claude_code_is_verified_locally() -> None:
    verified = DEFAULT_CATALOG.by_confidence(Confidence.VERIFIED_LOCAL)
    assert [t.name for t in verified] == ["Claude Code"]


def test_by_confidence_filters() -> None:
    catalog = Catalog(
        [
            CliTool("A", "x", "p", Confidence.OFFICIAL),
            CliTool("B", "x", None, Confidence.UNKNOWN),
        ]
    )
    assert [t.name for t in catalog.by_confidence(Confidence.OFFICIAL)] == ["A"]
    assert len(catalog) == 2
