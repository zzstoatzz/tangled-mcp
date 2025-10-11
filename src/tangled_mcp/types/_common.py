"""shared types and validators"""

from typing import Annotated

from pydantic import AfterValidator


def normalize_repo_identifier(v: str) -> str:
    """normalize repo identifier to owner/repo format without @ prefix"""
    if "/" not in v:
        raise ValueError(f"invalid repo format: '{v}'. expected 'owner/repo'")
    owner, repo_name = v.split("/", 1)
    # strip @ from owner if present
    owner = owner.lstrip("@")
    return f"{owner}/{repo_name}"


RepoIdentifier = Annotated[str, AfterValidator(normalize_repo_identifier)]
