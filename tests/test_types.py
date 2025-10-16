"""tests for public types API"""

import pytest
from pydantic import ValidationError

from tangled_mcp.types import (
    CreateIssueResult,
    ListBranchesResult,
    UpdateIssueResult,
)


class TestRepoIdentifierValidation:
    """test RepoIdentifier validation behavior"""

    def test_strips_at_prefix(self):
        """@ prefix is stripped during validation"""
        result = CreateIssueResult(repo="@owner/repo", issue_id=1)
        assert result.repo == "owner/repo"

    def test_accepts_without_at_prefix(self):
        """repo identifier without @ works"""
        result = CreateIssueResult(repo="owner/repo", issue_id=1)
        assert result.repo == "owner/repo"

    def test_rejects_invalid_format(self):
        """repo identifier without slash is rejected"""
        with pytest.raises(ValidationError, match="invalid repo format"):
            CreateIssueResult(repo="invalid", issue_id=1)


class TestIssueResultURLs:
    """test issue result URL generation"""

    def test_create_issue_url(self):
        """create result generates correct tangled.org URL"""
        result = CreateIssueResult(repo="owner/repo", issue_id=42)
        assert result.url == "https://tangled.org/@owner/repo/issues/42"

    def test_update_issue_url(self):
        """update result generates correct tangled.org URL"""
        result = UpdateIssueResult(repo="owner/repo", issue_id=42)
        assert result.url == "https://tangled.org/@owner/repo/issues/42"

    def test_url_handles_at_prefix_input(self):
        """URL is correct even when input has @ prefix"""
        result = CreateIssueResult(repo="@owner/repo", issue_id=42)
        assert result.url == "https://tangled.org/@owner/repo/issues/42"


class TestListBranchesFromAPIResponse:
    """test ListBranchesResult.from_api_response constructor"""

    def test_parses_branch_data(self):
        """parses branches from API response structure"""
        response = {
            "branches": [
                {"reference": {"name": "main", "hash": "abc123"}},
                {"reference": {"name": "dev", "hash": "def456"}},
            ],
        }

        result = ListBranchesResult.from_api_response(response)

        assert len(result.branches) == 2
        assert result.branches[0].name == "main"
        assert result.branches[0].sha == "abc123"
        assert result.branches[1].name == "dev"
        assert result.branches[1].sha == "def456"

    def test_handles_empty_branches(self):
        """handles empty branches list"""
        response = {"branches": []}

        result = ListBranchesResult.from_api_response(response)

        assert result.branches == []
