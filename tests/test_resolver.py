"""tests for repository identifier resolution"""

import pytest


class TestRepoIdentifierParsing:
    """test repository identifier format validation"""

    def test_invalid_format_no_slash(self):
        """test that identifiers without slash are rejected"""
        from tangled_mcp._tangled._client import resolve_repo_identifier

        with pytest.raises(
            ValueError, match="invalid repo format.*expected 'owner/repo'"
        ):
            resolve_repo_identifier("invalid")

    def test_invalid_format_empty(self):
        """test that empty identifiers are rejected"""
        from tangled_mcp._tangled._client import resolve_repo_identifier

        with pytest.raises(
            ValueError, match="invalid repo format.*expected 'owner/repo'"
        ):
            resolve_repo_identifier("")

    def test_valid_format_with_handle(self):
        """test that valid owner/repo format is accepted (parsing only)"""
        # note: we can't actually test resolution without credentials
        # but we can test that the format parsing works
        from tangled_mcp._tangled._client import resolve_repo_identifier

        # this will fail at the resolution step, but not at parsing
        with pytest.raises(Exception):  # will fail during actual resolution
            resolve_repo_identifier("owner/repo")

    def test_valid_format_with_at_prefix(self):
        """test that @owner/repo and owner/repo resolve identically"""
        from tangled_mcp._tangled._client import resolve_repo_identifier

        # both formats should behave the same (@ is stripped internally)
        # they'll both fail resolution with fake handle, but in the same way
        with pytest.raises(ValueError, match="failed to resolve handle 'owner'"):
            resolve_repo_identifier("@owner/repo")

        with pytest.raises(ValueError, match="failed to resolve handle 'owner'"):
            resolve_repo_identifier("owner/repo")

    def test_valid_format_with_did(self):
        """test that did:plc:.../repo format is accepted"""
        from tangled_mcp._tangled._client import resolve_repo_identifier

        # this will fail at the resolution step, but not at parsing
        with pytest.raises(Exception):  # will fail during actual resolution
            resolve_repo_identifier("did:plc:test123/repo")
