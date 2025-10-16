"""branch-related types"""

from typing import Any

from pydantic import BaseModel


class BranchInfo(BaseModel):
    """branch information"""

    name: str
    sha: str


class ListBranchesResult(BaseModel):
    """result of listing branches"""

    branches: list[BranchInfo]

    @classmethod
    def from_api_response(cls, response: dict[str, Any]) -> "ListBranchesResult":
        """construct from raw API response

        Args:
            response: raw response from tangled API with structure:
                {
                    "branches": [
                        {"reference": {"name": "main", "hash": "abc123"}},
                        ...
                    ]
                }

        Returns:
            ListBranchesResult with parsed branches
        """
        branches = []
        if "branches" in response:
            for branch_data in response["branches"]:
                ref = branch_data.get("reference", {})
                branches.append(
                    BranchInfo(
                        name=ref.get("name", ""),
                        sha=ref.get("hash", ""),
                    )
                )

        return cls(branches=branches)
