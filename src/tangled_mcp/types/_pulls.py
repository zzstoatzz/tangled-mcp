"""pull request types"""

from typing import Any

from pydantic import BaseModel, Field


class PullSource(BaseModel):
    """source branch info for a pull request"""

    sha: str
    branch: str
    repo: str | None = None  # AT-URI of source repo (for cross-repo PRs)


class PullTarget(BaseModel):
    """target branch info for a pull request"""

    repo: str  # AT-URI of target repo
    branch: str


class PullInfo(BaseModel):
    """pull request information"""

    uri: str
    cid: str
    title: str
    source: PullSource
    target: PullTarget
    created_at: str = Field(alias="createdAt")


class ListPullsResult(BaseModel):
    """result of listing pull requests"""

    pulls: list[PullInfo]

    @classmethod
    def from_api_response(cls, pulls_data: list[dict[str, Any]]) -> "ListPullsResult":
        """construct from pre-filtered pull data

        Args:
            pulls_data: list of pull dicts already filtered by target repo

        Returns:
            ListPullsResult with parsed pulls
        """
        pulls = []
        for pull in pulls_data:
            source = pull.get("source", {})
            target = pull.get("target", {})
            pulls.append(
                PullInfo(
                    uri=pull["uri"],
                    cid=pull["cid"],
                    title=pull.get("title", ""),
                    source=PullSource(
                        sha=source.get("sha", ""),
                        branch=source.get("branch", ""),
                        repo=source.get("repo"),
                    ),
                    target=PullTarget(
                        repo=target.get("repo", ""),
                        branch=target.get("branch", ""),
                    ),
                    createdAt=pull.get("createdAt", ""),
                )
            )
        return cls(pulls=pulls)
