"""issue-related types"""

from typing import Any

from pydantic import BaseModel, Field, computed_field

from tangled_mcp.types._common import RepoIdentifier


def _tangled_issue_url(repo: RepoIdentifier, issue_id: int) -> str:
    """construct clickable tangled.org URL"""
    owner, repo_name = repo.split("/", 1)
    return f"https://tangled.org/@{owner}/{repo_name}/issues/{issue_id}"


class IssueInfo(BaseModel):
    """issue information"""

    uri: str
    cid: str
    issue_id: int = Field(alias="issueId")
    title: str
    body: str | None = None
    created_at: str = Field(alias="createdAt")
    labels: list[str] = []


class CreateIssueResult(BaseModel):
    """result of creating an issue"""

    repo: RepoIdentifier
    issue_id: int

    @computed_field
    @property
    def url(self) -> str:
        """construct clickable tangled.org URL"""
        return _tangled_issue_url(self.repo, self.issue_id)


class UpdateIssueResult(BaseModel):
    """result of updating an issue"""

    repo: RepoIdentifier
    issue_id: int

    @computed_field
    @property
    def url(self) -> str:
        """construct clickable tangled.org URL"""
        return _tangled_issue_url(self.repo, self.issue_id)


class DeleteIssueResult(BaseModel):
    """result of deleting an issue"""

    issue_id: int


class ListIssuesResult(BaseModel):
    """result of listing issues"""

    issues: list[IssueInfo]

    @classmethod
    def from_api_response(cls, response: dict[str, Any]) -> "ListIssuesResult":
        """construct from raw API response

        Args:
            response: raw response from tangled API with structure:
                {
                    "issues": [
                        {
                            "uri": "at://...",
                            "cid": "bafyrei...",
                            "issueId": 1,
                            "title": "...",
                            "body": "...",
                            "createdAt": "..."
                        },
                        ...
                    ]
                }

        Returns:
            ListIssuesResult with parsed issues
        """
        issues = [IssueInfo(**issue_data) for issue_data in response.get("issues", [])]
        return cls(issues=issues)
