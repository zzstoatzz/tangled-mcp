"""type definitions for tangled MCP server"""

from typing import Any

from pydantic import BaseModel, Field


class RepoInfo(BaseModel):
    """repository information"""

    name: str
    knot: str
    description: str | None = None
    created_at: str = Field(alias="createdAt")


class IssueInfo(BaseModel):
    """issue information"""

    repo: str
    title: str
    body: str | None = None
    created_at: str = Field(alias="createdAt")


class PullInfo(BaseModel):
    """pull request information"""

    title: str
    body: str | None = None
    patch: str
    target_repo: str
    target_branch: str
    source_branch: str | None = None
    source_sha: str | None = None
    created_at: str = Field(alias="createdAt")


class BranchInfo(BaseModel):
    """branch information"""

    name: str
    sha: str


class CreateIssueResult(BaseModel):
    """result of creating an issue"""

    uri: str
    success: bool = True
    message: str = "issue created successfully"


class CreateRepoResult(BaseModel):
    """result of creating a repository"""

    uri: str
    success: bool = True
    message: str = "repository created successfully"


class ListBranchesResult(BaseModel):
    """result of listing branches"""

    branches: list[BranchInfo]
    cursor: str | None = None


class GenericResult(BaseModel):
    """generic operation result"""

    success: bool
    message: str
    data: dict[str, Any] | None = None
