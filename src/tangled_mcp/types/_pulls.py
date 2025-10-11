"""pull request-related types"""

from typing import Any

from pydantic import BaseModel, Field, computed_field

from tangled_mcp.types._common import RepoIdentifier


def _tangled_pull_url(repo: RepoIdentifier, pull_id: int) -> str:
    """construct clickable tangled.org URL"""
    owner, repo_name = repo.split("/", 1)
    return f"https://tangled.org/@{owner}/{repo_name}/pulls/{pull_id}"


class PullInfo(BaseModel):
    """pull request information"""

    uri: str
    cid: str
    pull_id: int = Field(alias="pullId")
    title: str
    body: str | None = None
    base: str  # target branch
    head: str  # source branch
    sha: str | None = None  # commit hash
    created_at: str = Field(alias="createdAt")
    labels: list[str] = []


class CreatePullResult(BaseModel):
    """result of creating a pull request"""

    repo: RepoIdentifier
    pull_id: int

    @computed_field
    @property
    def url(self) -> str:
        """construct clickable tangled.org URL"""
        return _tangled_pull_url(self.repo, self.pull_id)


class UpdatePullResult(BaseModel):
    """result of updating a pull request"""

    repo: RepoIdentifier
    pull_id: int

    @computed_field
    @property
    def url(self) -> str:
        """construct clickable tangled.org URL"""
        return _tangled_pull_url(self.repo, self.pull_id)


class ListPullsResult(BaseModel):
    """result of listing pull requests"""

    pulls: list[PullInfo]
    cursor: str | None = None

    @classmethod
    def from_api_response(cls, response: dict[str, Any]) -> "ListPullsResult":
        """construct from raw API response

        Args:
            response: raw response from tangled API with structure:
                {
                    "pulls": [
                        {
                            "uri": "at://...",
                            "cid": "bafyrei...",
                            "pullId": 1,
                            "title": "...",
                            "body": "...",
                            "base": "main",
                            "head": "feature",
                            "sha": "abc123...",
                            "createdAt": "..."
                        },
                        ...
                    ],
                    "cursor": "optional_cursor"
                }

        Returns:
            ListPullsResult with parsed pull requests
        """
        pulls = [PullInfo(**pull_data) for pull_data in response.get("pulls", [])]
        return cls(pulls=pulls, cursor=response.get("cursor"))
