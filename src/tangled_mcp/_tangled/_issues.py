"""issue operations for tangled"""

from datetime import datetime, timezone
from typing import Any

from atproto import models

from tangled_mcp._tangled._client import _get_authenticated_client


def create_issue(
    repo_id: str, title: str, body: str | None = None, labels: list[str] | None = None
) -> dict[str, Any]:
    """create an issue on a repository

    Args:
        repo_id: repository identifier in "did/repo" format (e.g., 'did:plc:.../tangled-mcp')
        title: issue title
        body: optional issue body/description
        labels: optional list of label names (e.g., ["good-first-issue", "bug"])
                or full label definition URIs (e.g., ["at://did:.../sh.tangled.label.definition/bug"])

    Returns:
        dict with uri, cid, and issueId of created issue record
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

    # query existing issues to determine next issueId
    existing_issues = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=client.me.did,
            collection="sh.tangled.repo.issue",
            limit=100,
        )
    )

    # find max issueId for this repo
    max_issue_id = 0
    for issue_record in existing_issues.records:
        if (
            repo := getattr(issue_record.value, "repo", None)
        ) is not None and repo == repo_at_uri:
            issue_id = getattr(issue_record.value, "issueId", None)
            if issue_id is not None:
                max_issue_id = max(max_issue_id, issue_id)

    next_issue_id = max_issue_id + 1

    # validate labels BEFORE creating the issue to prevent orphaned issues
    if labels:
        _validate_labels(labels, repo_labels)

    # generate timestamp ID for rkey
    tid = int(datetime.now(timezone.utc).timestamp() * 1000000)
    rkey = str(tid)

    # create issue record with proper schema
    record = {
        "$type": "sh.tangled.repo.issue",
        "repo": repo_at_uri,  # full AT-URI of repo record
        "issueId": next_issue_id,  # sequential issue ID
        "owner": client.me.did,  # issue creator's DID
        "title": title,
        "body": body,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    # use putRecord to create the issue
    response = client.com.atproto.repo.put_record(
        models.ComAtprotoRepoPutRecord.Data(
            repo=client.me.did,
            collection="sh.tangled.repo.issue",
            rkey=rkey,
            record=record,
        )
    )

    issue_uri = response.uri
    result = {"uri": issue_uri, "cid": response.cid, "issueId": next_issue_id}

    # if labels were specified, create a label op to add them
    if labels:
        _apply_labels(client, issue_uri, labels, repo_labels, current_labels=set())

    return result


def update_issue(
    repo_id: str,
    issue_id: int,
    title: str | None = None,
    body: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """update an existing issue on a repository

    Args:
        repo_id: repository identifier in "did/repo" format (e.g., 'did:plc:.../tangled-mcp')
        issue_id: the sequential issue number (e.g., 1, 2, 3...)
        title: optional new issue title (if None, keeps existing)
        body: optional new issue body (if None, keeps existing)
        labels: optional list of label names to SET (replaces all existing labels)
                use empty list [] to remove all labels

    Returns:
        dict with uri and cid of updated issue record
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

    # find the issue record with matching issueId
    existing_issues = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=client.me.did,
            collection="sh.tangled.repo.issue",
            limit=100,
        )
    )

    issue_record = None
    issue_rkey = None
    for record in existing_issues.records:
        if (
            (repo := getattr(record.value, "repo", None)) is not None
            and repo == repo_at_uri
            and (_issue_id := getattr(record.value, "issueId", None)) is not None
            and _issue_id == issue_id
        ):
            issue_record = record
            issue_rkey = record.uri.split("/")[-1]  # extract rkey from AT-URI
            break

    if not issue_record:
        raise ValueError(f"issue #{issue_id} not found in repo {repo_id}")

    # update the issue fields (keep existing if not specified)
    updated_record = {
        "$type": "sh.tangled.repo.issue",
        "repo": repo_at_uri,
        "issueId": issue_id,
        "owner": (
            (owner := getattr(issue_record.value, "owner", None)) is not None and owner
            if hasattr(issue_record.value, "owner")
            else client.me.did
        ),
        "title": title
        if title is not None
        else getattr(issue_record.value, "title", None),
        "body": body if body is not None else getattr(issue_record.value, "body", None),
        "createdAt": getattr(issue_record.value, "createdAt", None),
    }

    # get current CID for swap
    current_cid = issue_record.cid

    # update the issue record

    if issue_rkey is None:
        raise ValueError(
            f"issue rkey not found for issue #{issue_id} in repo {repo_id}"
        )

    response = client.com.atproto.repo.put_record(
        models.ComAtprotoRepoPutRecord.Data(
            repo=client.me.did,
            collection="sh.tangled.repo.issue",
            rkey=issue_rkey,
            record=updated_record,
            swap_record=current_cid,  # ensure we're updating the right version
        )
    )

    result = {"uri": response.uri, "cid": response.cid}

    # if labels were specified, create a label op to set them
    if labels is not None:
        issue_uri = response.uri

        # get current label state for this issue
        current_labels = _get_current_labels(client, issue_uri)

        # apply the new label state
        _apply_labels(client, issue_uri, labels, repo_labels, current_labels)

    return result


def delete_issue(repo_id: str, issue_id: int) -> dict[str, str]:
    """delete an issue from a repository

    Args:
        repo_id: repository identifier in "did/repo" format (e.g., 'did:plc:.../tangled-mcp')
        issue_id: the sequential issue number (e.g., 1, 2, 3...)

    Returns:
        dict with uri of deleted issue record
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

    # find the issue record with matching issueId
    existing_issues = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=client.me.did,
            collection="sh.tangled.repo.issue",
            limit=100,
        )
    )

    issue_uri = None
    issue_rkey = None
    for record in existing_issues.records:
        if (
            (repo := getattr(record.value, "repo", None)) is not None
            and repo == repo_at_uri
            and (_issue_id := getattr(record.value, "issueId", None)) is not None
            and _issue_id == issue_id
        ):
            issue_uri = record.uri
            issue_rkey = record.uri.split("/")[-1]
            break

    if not issue_uri or not issue_rkey:
        raise ValueError(f"issue #{issue_id} not found in repo {repo_id}")

    # delete the issue record
    client.com.atproto.repo.delete_record(
        models.ComAtprotoRepoDeleteRecord.Data(
            repo=client.me.did,
            collection="sh.tangled.repo.issue",
            rkey=issue_rkey,
        )
    )

    return {"uri": issue_uri}


def list_repo_issues(
    repo_id: str, limit: int = 50, cursor: str | None = None
) -> dict[str, Any]:
    """list issues for a repository

    Args:
        repo_id: repository identifier in "did/repo" format
        limit: maximum number of issues to return
        cursor: pagination cursor

    Returns:
        dict containing issues and optional cursor
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

    # list records from the issue collection
    response = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=client.me.did,
            collection="sh.tangled.repo.issue",
            limit=limit,
            cursor=cursor,
        )
    )

    # filter issues by repo
    issues = []
    issue_uris = []
    for record in response.records:
        if (
            repo := getattr(record.value, "repo", None)
        ) is not None and repo == repo_at_uri:
            issue_uris.append(record.uri)
            issues.append(
                {
                    "uri": record.uri,
                    "cid": record.cid,
                    "issueId": getattr(record.value, "issueId", 0),
                    "title": getattr(record.value, "title", ""),
                    "body": getattr(record.value, "body", None),
                    "createdAt": getattr(record.value, "createdAt", ""),
                    "labels": [],  # will be populated below
                }
            )

    # fetch label ops and correlate with issues
    if issue_uris:
        label_ops = client.com.atproto.repo.list_records(
            models.ComAtprotoRepoListRecords.Params(
                repo=client.me.did,
                collection="sh.tangled.label.op",
                limit=100,
            )
        )

        # build map of issue_uri -> current label URIs
        issue_labels_map: dict[str, set[str]] = {uri: set() for uri in issue_uris}
        for op_record in label_ops.records:
            if (
                hasattr(op_record.value, "subject")
                and op_record.value.subject in issue_labels_map
            ):
                subject_uri = op_record.value.subject
                if hasattr(op_record.value, "add"):
                    for operand in op_record.value.add:
                        if hasattr(operand, "key"):
                            issue_labels_map[subject_uri].add(operand.key)
                if hasattr(op_record.value, "delete"):
                    for operand in op_record.value.delete:
                        if hasattr(operand, "key"):
                            issue_labels_map[subject_uri].discard(operand.key)

        # extract label names from URIs and add to issues
        for issue in issues:
            label_uris = issue_labels_map.get(issue["uri"], set())
            issue["labels"] = [uri.split("/")[-1] for uri in label_uris]

    return {"issues": issues, "cursor": response.cursor}


def list_repo_labels(repo_id: str) -> list[str]:
    """list available labels for a repository

    Args:
        repo_id: repository identifier in "did/repo" format

    Returns:
        list of available label names for the repo
    """
    client = _get_authenticated_client()

    if not client.me:
        raise RuntimeError("client not authenticated")

    # parse repo_id to get owner_did and repo_name
    if "/" not in repo_id:
        raise ValueError(f"invalid repo_id format: {repo_id}")

    owner_did, repo_name = repo_id.split("/", 1)

    # get the repo's subscribed label definitions
    records = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=owner_did,
            collection="sh.tangled.repo",
            limit=100,
        )
    )

    repo_labels: list[str] = []
    for record in records.records:
        if (
            name := getattr(record.value, "name", None)
        ) is not None and name == repo_name:
            if (subscribed_labels := getattr(record.value, "labels", None)) is not None:
                # extract label names from URIs
                repo_labels = [uri.split("/")[-1] for uri in subscribed_labels]
            break

    if not repo_labels and not any(
        (name := getattr(r.value, "name", None)) and name == repo_name
        for r in records.records
    ):
        raise ValueError(f"repo not found: {repo_id}")

    return repo_labels


def _get_current_labels(client, issue_uri: str) -> set[str]:
    """get current labels applied to an issue by examining all label ops"""
    label_ops = client.com.atproto.repo.list_records(
        models.ComAtprotoRepoListRecords.Params(
            repo=client.me.did,
            collection="sh.tangled.label.op",
            limit=100,
        )
    )

    # collect all label ops for this issue to determine current state
    current_labels = set()
    for op_record in label_ops.records:
        if hasattr(op_record.value, "subject") and op_record.value.subject == issue_uri:
            if hasattr(op_record.value, "add"):
                for operand in op_record.value.add:
                    if hasattr(operand, "key"):
                        current_labels.add(operand.key)
            if hasattr(op_record.value, "delete"):
                for operand in op_record.value.delete:
                    if hasattr(operand, "key"):
                        current_labels.discard(operand.key)

    return current_labels


def _validate_labels(labels: list[str], repo_labels: list[str]) -> None:
    """validate that all requested labels exist in the repo's subscribed labels

    Args:
        labels: list of label names or URIs to validate
        repo_labels: list of label definition URIs the repo subscribes to

    Raises:
        ValueError: if any labels are invalid, listing available labels
    """
    # extract available label names from repo's subscribed label URIs
    available_labels = [uri.split("/")[-1] for uri in repo_labels]

    # check each requested label
    invalid_labels = []
    for label in labels:
        if label.startswith("at://"):
            # if it's a full URI, check if it's in repo_labels
            if label not in repo_labels:
                invalid_labels.append(label)
        else:
            # if it's a name, check if it matches any available label
            if not any(
                label.lower() == available.lower() for available in available_labels
            ):
                invalid_labels.append(label)

    # fail loudly if any labels are invalid
    if invalid_labels:
        raise ValueError(
            f"invalid labels: {invalid_labels}\n"
            f"available labels for this repo: {sorted(available_labels)}"
        )


def _apply_labels(
    client,
    issue_uri: str,
    labels: list[str],
    repo_labels: list[str],
    current_labels: set[str],
) -> None:
    """apply a set of labels to an issue, creating a label op record

    Args:
        client: authenticated atproto client
        issue_uri: AT-URI of the issue
        labels: list of label names or URIs to apply
        repo_labels: list of label definition URIs the repo subscribes to
        current_labels: set of currently applied label URIs

    Raises:
        ValueError: if any labels are invalid (via _validate_labels)
    """
    # validate labels before attempting to apply
    _validate_labels(labels, repo_labels)

    # resolve label names to URIs
    new_label_uris = set()
    for label in labels:
        if label.startswith("at://"):
            new_label_uris.add(label)
        else:
            for repo_label_uri in repo_labels:
                label_name = repo_label_uri.split("/")[-1]
                if label_name.lower() == label.lower():
                    new_label_uris.add(repo_label_uri)
                    break

    # calculate diff: what to add and what to delete
    labels_to_add = new_label_uris - current_labels
    labels_to_delete = current_labels - new_label_uris

    # only create label op if there are changes
    if labels_to_add or labels_to_delete:
        label_op_tid = int(datetime.now(timezone.utc).timestamp() * 1000000)
        label_op_rkey = str(label_op_tid)

        label_op_record = {
            "$type": "sh.tangled.label.op",
            "subject": issue_uri,
            "add": [{"key": label_uri, "value": ""} for label_uri in labels_to_add],
            "delete": [
                {"key": label_uri, "value": ""} for label_uri in labels_to_delete
            ],
            "performedAt": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }

        client.com.atproto.repo.put_record(
            models.ComAtprotoRepoPutRecord.Data(
                repo=client.me.did,
                collection="sh.tangled.label.op",
                rkey=label_op_rkey,
                record=label_op_record,
            )
        )
