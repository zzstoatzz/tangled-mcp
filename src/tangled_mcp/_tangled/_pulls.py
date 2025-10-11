"""pull request operations for tangled"""

from datetime import datetime, timezone
from typing import Any

from atproto import models

from tangled_mcp._tangled._client import _get_authenticated_client
from tangled_mcp._tangled._issues import (
    _apply_labels,
    _get_current_labels,
    _validate_labels,
)


def create_repo_pull(
    repo_id: str,
    title: str,
    base: str,
    head: str,
    patch: str,
    body: str | None = None,
    source_sha: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """create a pull request on a repository

    Args:
        repo_id: repository identifier in "did/repo" format (e.g., 'did:plc:.../tangled-mcp')
        title: pull request title
        base: target branch (e.g., 'main')
        head: source branch (e.g., 'feature-branch')
        patch: git diff content
        body: optional pull request description
        source_sha: optional 40-character commit hash
        labels: optional list of label names (e.g., ["enhancement", "needs-review"])

    Returns:
        dict with uri, cid, and pullId of created pull request record
    """
    client = _get_authenticated_client()

    if not client.me:
        raise RuntimeError("client not authenticated")

    # parse repo_id to get owner_did and repo_name
    if "/" not in repo_id:
        raise ValueError(f"invalid repo_id format: {repo_id}")

    owner_did, repo_name = repo_id.split("/", 1)

    # get the repo AT-URI and label definitions by querying the repo collection
    records = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=owner_did,
            collection="sh.tangled.repo",
            limit=100,
        )
    )

    repo_at_uri = None
    repo_labels: list[str] = []
    for record in records.records:
        if (
            name := getattr(record.value, "name", None)
        ) is not None and name == repo_name:
            repo_at_uri = record.uri
            # get repo's subscribed labels
            if (subscribed_labels := getattr(record.value, "labels", None)) is not None:
                repo_labels = subscribed_labels
            break

    if not repo_at_uri:
        raise ValueError(f"repo not found: {repo_id}")

    # query existing pulls to determine next pullId
    existing_pulls = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=client.me.did,
            collection="sh.tangled.repo.pull",
            limit=100,
        )
    )

    # find max pullId for this repo
    max_pull_id = 0
    for pull_record in existing_pulls.records:
        if (
            target := getattr(pull_record.value, "target", None)
        ) is not None and getattr(target, "repo", None) == repo_at_uri:
            pull_id = getattr(pull_record.value, "pullId", None)
            if pull_id is not None:
                max_pull_id = max(max_pull_id, pull_id)

    next_pull_id = max_pull_id + 1

    # generate timestamp ID for rkey
    tid = int(datetime.now(timezone.utc).timestamp() * 1000000)
    rkey = str(tid)

    # create pull request record with proper schema
    record: dict[str, Any] = {
        "$type": "sh.tangled.repo.pull",
        "target": {
            "repo": repo_at_uri,  # full AT-URI of repo record
            "branch": base,
        },
        "pullId": next_pull_id,  # sequential pull ID (client extension)
        "title": title,
        "patch": patch,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    # add optional fields
    if body is not None:
        record["body"] = body

    if source_sha is not None:
        # validate sha is 40 characters (git full hash)
        if len(source_sha) != 40:
            raise ValueError(
                f"source_sha must be 40 characters (got {len(source_sha)})"
            )
        record["source"] = {
            "branch": head,
            "sha": source_sha,
        }

    # use putRecord to create the pull request
    response = client.com.atproto.repo.put_record(
        models.ComAtprotoRepoPutRecord.Data(
            repo=client.me.did,
            collection="sh.tangled.repo.pull",
            rkey=rkey,
            record=record,
        )
    )

    pull_uri = response.uri
    result = {"uri": pull_uri, "cid": response.cid, "pullId": next_pull_id}

    # if labels were specified, create a label op to add them
    if labels:
        _apply_labels(client, pull_uri, labels, repo_labels, current_labels=set())

    return result


def list_repo_pulls(
    repo_id: str, limit: int = 50, cursor: str | None = None
) -> dict[str, Any]:
    """list pull requests for a repository

    Args:
        repo_id: repository identifier in "did/repo" format
        limit: maximum number of pull requests to return
        cursor: pagination cursor

    Returns:
        dict containing pulls and optional cursor
    """
    client = _get_authenticated_client()

    if not client.me:
        raise RuntimeError("client not authenticated")

    # parse repo_id to get owner_did and repo_name
    if "/" not in repo_id:
        raise ValueError(f"invalid repo_id format: {repo_id}")

    owner_did, repo_name = repo_id.split("/", 1)

    # get the repo AT-URI by querying the repo collection
    records = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=owner_did,
            collection="sh.tangled.repo",
            limit=100,
        )
    )

    repo_at_uri = None
    for record in records.records:
        if (
            name := getattr(record.value, "name", None)
        ) is not None and name == repo_name:
            repo_at_uri = record.uri
            break

    if not repo_at_uri:
        raise ValueError(f"repo not found: {repo_id}")

    # list records from the pull collection
    response = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=client.me.did,
            collection="sh.tangled.repo.pull",
            limit=limit,
            cursor=cursor,
        )
    )

    # filter pulls by repo
    pulls = []
    pull_uris = []
    for record in response.records:
        if (
            target := getattr(record.value, "target", None)
        ) is not None and getattr(target, "repo", None) == repo_at_uri:
            pull_uris.append(record.uri)
            source = getattr(record.value, "source", None)
            pulls.append(
                {
                    "uri": record.uri,
                    "cid": record.cid,
                    "pullId": getattr(record.value, "pullId", 0),
                    "title": getattr(record.value, "title", ""),
                    "body": getattr(record.value, "body", None),
                    "base": getattr(target, "branch", ""),
                    "head": getattr(source, "branch", "") if source else "",
                    "sha": getattr(source, "sha", None) if source else None,
                    "createdAt": getattr(record.value, "createdAt", ""),
                    "labels": [],  # will be populated below
                }
            )

    # fetch label ops and correlate with pulls
    if pull_uris:
        label_ops = client.com.atproto.repo.list_records(
            models.ComAtprotoRepoListRecords.Params(
                repo=client.me.did,
                collection="sh.tangled.label.op",
                limit=100,
            )
        )

        # build map of pull_uri -> current label URIs
        pull_labels_map: dict[str, set[str]] = {uri: set() for uri in pull_uris}
        for op_record in label_ops.records:
            if (
                hasattr(op_record.value, "subject")
                and op_record.value.subject in pull_labels_map
            ):
                subject_uri = op_record.value.subject
                if hasattr(op_record.value, "add"):
                    for operand in op_record.value.add:
                        if hasattr(operand, "key"):
                            pull_labels_map[subject_uri].add(operand.key)
                if hasattr(op_record.value, "delete"):
                    for operand in op_record.value.delete:
                        if hasattr(operand, "key"):
                            pull_labels_map[subject_uri].discard(operand.key)

        # extract label names from URIs and add to pulls
        for pull in pulls:
            label_uris = pull_labels_map.get(pull["uri"], set())
            pull["labels"] = [uri.split("/")[-1] for uri in label_uris]

    return {"pulls": pulls, "cursor": response.cursor}


def get_repo_pull(repo_id: str, pull_id: int) -> dict[str, Any]:
    """get detailed information about a specific pull request

    Args:
        repo_id: repository identifier in "did/repo" format
        pull_id: the sequential pull request number (e.g., 1, 2, 3...)

    Returns:
        dict with pull request details
    """
    client = _get_authenticated_client()

    if not client.me:
        raise RuntimeError("client not authenticated")

    # parse repo_id to get owner_did and repo_name
    if "/" not in repo_id:
        raise ValueError(f"invalid repo_id format: {repo_id}")

    owner_did, repo_name = repo_id.split("/", 1)

    # get the repo AT-URI
    records = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=owner_did,
            collection="sh.tangled.repo",
            limit=100,
        )
    )

    repo_at_uri = None
    for record in records.records:
        if (
            name := getattr(record.value, "name", None)
        ) is not None and name == repo_name:
            repo_at_uri = record.uri
            break

    if not repo_at_uri:
        raise ValueError(f"repo not found: {repo_id}")

    # find the pull request record with matching pullId
    existing_pulls = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=client.me.did,
            collection="sh.tangled.repo.pull",
            limit=100,
        )
    )

    pull_record = None
    for record in existing_pulls.records:
        if (
            (target := getattr(record.value, "target", None)) is not None
            and getattr(target, "repo", None) == repo_at_uri
            and (_pull_id := getattr(record.value, "pullId", None)) is not None
            and _pull_id == pull_id
        ):
            pull_record = record
            break

    if not pull_record:
        raise ValueError(f"pull request #{pull_id} not found in repo {repo_id}")

    # get labels for this pull request
    pull_uri = pull_record.uri
    current_labels = _get_current_labels(client, pull_uri)
    label_names = [uri.split("/")[-1] for uri in current_labels]

    # build result
    target = getattr(pull_record.value, "target", None)
    source = getattr(pull_record.value, "source", None)

    result = {
        "uri": pull_uri,
        "cid": pull_record.cid,
        "pullId": pull_id,
        "title": getattr(pull_record.value, "title", ""),
        "body": getattr(pull_record.value, "body", None),
        "base": getattr(target, "branch", "") if target else "",
        "head": getattr(source, "branch", "") if source else "",
        "sha": getattr(source, "sha", None) if source else None,
        "patch": getattr(pull_record.value, "patch", ""),
        "createdAt": getattr(pull_record.value, "createdAt", ""),
        "labels": label_names,
    }

    return result


def update_repo_pull(
    repo_id: str,
    pull_id: int,
    title: str | None = None,
    body: str | None = None,
    base: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """update an existing pull request on a repository

    Args:
        repo_id: repository identifier in "did/repo" format
        pull_id: the sequential pull request number (e.g., 1, 2, 3...)
        title: optional new pull request title (if None, keeps existing)
        body: optional new pull request body (if None, keeps existing)
        base: optional new target branch (if None, keeps existing)
        labels: optional list of label names to SET (replaces all existing labels)
                use empty list [] to remove all labels

    Returns:
        dict with uri and cid of updated pull request record
    """
    client = _get_authenticated_client()

    if not client.me:
        raise RuntimeError("client not authenticated")

    # parse repo_id to get owner_did and repo_name
    if "/" not in repo_id:
        raise ValueError(f"invalid repo_id format: {repo_id}")

    owner_did, repo_name = repo_id.split("/", 1)

    # get the repo AT-URI and label definitions
    records = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=owner_did,
            collection="sh.tangled.repo",
            limit=100,
        )
    )

    repo_at_uri = None
    repo_labels: list[str] = []
    for record in records.records:
        if (name := getattr(record.value, "name", None)) and name == repo_name:
            repo_at_uri = record.uri
            if (subscribed_labels := getattr(record.value, "labels", None)) is not None:
                repo_labels = subscribed_labels
            break

    if not repo_at_uri:
        raise ValueError(f"repo not found: {repo_id}")

    # find the pull request record with matching pullId
    existing_pulls = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=client.me.did,
            collection="sh.tangled.repo.pull",
            limit=100,
        )
    )

    pull_record = None
    pull_rkey = None
    for record in existing_pulls.records:
        if (
            (target := getattr(record.value, "target", None)) is not None
            and getattr(target, "repo", None) == repo_at_uri
            and (_pull_id := getattr(record.value, "pullId", None)) is not None
            and _pull_id == pull_id
        ):
            pull_record = record
            pull_rkey = record.uri.split("/")[-1]  # extract rkey from AT-URI
            break

    if not pull_record:
        raise ValueError(f"pull request #{pull_id} not found in repo {repo_id}")

    # get existing values
    existing_target = getattr(pull_record.value, "target", None)
    existing_source = getattr(pull_record.value, "source", None)

    # update the pull request fields (keep existing if not specified)
    updated_record: dict[str, Any] = {
        "$type": "sh.tangled.repo.pull",
        "target": {
            "repo": repo_at_uri,
            "branch": base if base is not None else getattr(existing_target, "branch", ""),
        },
        "pullId": pull_id,
        "title": title
        if title is not None
        else getattr(pull_record.value, "title", ""),
        "patch": getattr(pull_record.value, "patch", ""),
        "createdAt": getattr(pull_record.value, "createdAt", ""),
    }

    # preserve body if exists
    existing_body = getattr(pull_record.value, "body", None)
    if body is not None:
        updated_record["body"] = body
    elif existing_body is not None:
        updated_record["body"] = existing_body

    # preserve source if exists
    if existing_source is not None:
        updated_record["source"] = {
            "branch": getattr(existing_source, "branch", ""),
            "sha": getattr(existing_source, "sha", ""),
        }

    # get current CID for swap
    current_cid = pull_record.cid

    # update the pull request record
    if pull_rkey is None:
        raise ValueError(
            f"pull request rkey not found for pull #{pull_id} in repo {repo_id}"
        )

    response = client.com.atproto.repo.put_record(
        models.ComAtprotoRepoPutRecord.Data(
            repo=client.me.did,
            collection="sh.tangled.repo.pull",
            rkey=pull_rkey,
            record=updated_record,
            swap_record=current_cid,  # ensure we're updating the right version
        )
    )

    result = {"uri": response.uri, "cid": response.cid}

    # if labels were specified, create a label op to set them
    if labels is not None:
        pull_uri = response.uri

        # get current label state for this pull request
        current_labels = _get_current_labels(client, pull_uri)

        # apply the new label state
        _apply_labels(client, pull_uri, labels, repo_labels, current_labels)

    return result
