import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from tangled_mcp import bobbin, records, server
from tangled_mcp.records import tid

FIXTURES = Path(__file__).parent / "fixtures"
REPO_DID = "did:plc:ebajxjsw7iuwstddnxt6lt3m"
OWNER_DID = "did:plc:xbtmt2zjwlrfegqvch7fboei"
KNOT = "knot1.tangled.sh"
BOBBIN = "api.tangled.org"
TICKET_26 = f"at://{REPO_DID}/org.tangled.track.ticket/26"


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def did_doc(endpoint: str) -> dict[str, Any]:
    return {
        "service": [{"type": "AtprotoPersonalDataServer", "serviceEndpoint": endpoint}]
    }


class World:
    """a fake tangled: bobbin, one knot, plc, and whatever extra routes a test
    adds. records every request so tests can assert where reads went."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[tuple[str, str], Any] = {
            (BOBBIN, "org.tangled.repo.getRepoByName"): fixture("repo_by_name"),
            (BOBBIN, "org.tangled.repo.getRepoByRepoDid"): fixture("repo_by_name"),
            (BOBBIN, "org.tangled.repo.listIssues"): fixture("list_issues"),
            (BOBBIN, "org.tangled.repo.listPulls"): fixture("list_pulls"),
            (BOBBIN, "org.tangled.repo.listRepos"): fixture("list_repos"),
            (BOBBIN, "org.tangled.search.query"): fixture("search"),
            (BOBBIN, "org.tangled.track.getTicketView"): fixture("ticket_view"),
            (KNOT, "org.tangled.git.getTree"): fixture("tree"),
            (KNOT, "org.tangled.git.listBranches"): fixture("branches"),
            (KNOT, "org.tangled.git.listTags"): fixture("tags"),
            (KNOT, "org.tangled.git.listCommits"): fixture("commits"),
            (KNOT, "org.tangled.git.listLanguages"): fixture("languages"),
            (KNOT, "org.tangled.git.getDiff"): fixture("diff"),
            (KNOT, "com.atproto.repo.listRecords"): {"records": []},
            ("plc.directory", "*"): did_doc(f"https://{KNOT}"),
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        nsid = path.rsplit("/", 1)[-1]
        found = self.routes.get((host, nsid), self.routes.get((host, "*")))
        if found is None:
            return httpx.Response(404, json={"error": "NotFound", "message": path})
        if callable(found):
            return found(request)
        return httpx.Response(200, json=found)

    def hosts(self, nsid: str) -> set[str]:
        return {r.url.host for r in self.requests if r.url.path.endswith(nsid)}


@pytest.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    w = World()
    async with httpx.AsyncClient(transport=httpx.MockTransport(w.handle)) as client:
        monkeypatch.setattr(bobbin, "_client", client)
        yield w


async def test_tools_registered():
    tools = await server.tangled_mcp.list_tools()
    assert {
        "search",
        "get_record",
        "list_repos",
        "get_repo",
        "list_branches",
        "list_tags",
        "list_files",
        "read_file",
        "commit_log",
        "compare",
        "list_issues",
        "get_issue",
        "list_pulls",
        "get_pull",
        "list_pipelines",
        "create_issue",
        "create_pull",
        "update_pull",
        "get_pull_file",
        "get_pull_patch",
        "update_issue",
        "set_issue_state",
        "set_pull_state",
        "comment_on_issue",
        "comment_on_pull",
        "delete_issue",
    } <= {tool.name for tool in tools}


# --- repo resolution ---------------------------------------------------------


async def test_resolve_repo_by_owner_and_name(world: World, monkeypatch):
    monkeypatch.setattr(bobbin, "resolve_handle", AsyncMock(return_value=OWNER_DID))
    r = await bobbin.resolve_repo("@zzstoatzz.io/bot")
    assert (r.name, r.repo_did, r.knot, r.default_branch) == (
        "bot",
        REPO_DID,
        KNOT,
        "main",
    )
    [lookup] = [q for q in world.requests if "getRepoByName" in q.url.path]
    assert lookup.url.params["owner"] == OWNER_DID  # bobbin rejects handles here


@pytest.mark.parametrize(
    "identifier",
    [REPO_DID, f"at://{REPO_DID}/org.tangled.repo.manifest/self"],
)
async def test_resolve_repo_by_repo_did(world: World, identifier: str):
    r = await bobbin.resolve_repo(identifier)
    assert r.repo_did == REPO_DID
    assert world.hosts("getRepoByRepoDid") == {BOBBIN}


async def test_resolve_repo_follows_a_legacy_repo_uri_by_name(world: World):
    r = await bobbin.resolve_repo(f"at://{OWNER_DID}/sh.tangled.repo/bot")
    assert r.repo_did == REPO_DID
    [lookup] = [q for q in world.requests if "getRepoByName" in q.url.path]
    assert lookup.url.params["name"] == "bot"


async def test_resolve_repo_not_found(world: World, monkeypatch):
    monkeypatch.setattr(bobbin, "resolve_handle", AsyncMock(return_value=OWNER_DID))
    world.routes[(BOBBIN, "org.tangled.repo.getRepoByName")] = lambda _: (
        httpx.Response(
            404, json={"error": "RecordNotFound", "message": "record not found"}
        )
    )
    with pytest.raises(ValueError, match="not found"):
        await bobbin.resolve_repo("zzstoatzz.io/nope")


async def test_resolve_repo_rejects_bad_format():
    with pytest.raises(ValueError, match="owner/repo"):
        await bobbin.resolve_repo("just-a-name")


# --- git reads come from the knot ------------------------------------------------


async def test_git_reads_go_to_the_knot_by_repo_did(world: World):
    world.routes[(KNOT, "org.tangled.git.getBlob")] = lambda _: httpx.Response(
        200, content="phi — a bluesky bot.\n".encode()
    )
    files = await server.list_files(REPO_DID, path="src/bot/core")
    assert files[0] == {"name": "__init__.py", "is_dir": False, "size": 0}
    assert (
        await server.read_file(REPO_DID, path="AGENTS.md") == "phi — a bluesky bot.\n"
    )
    commits = await server.commit_log(REPO_DID, limit=2)
    assert commits[0]["sha"] == "6f33ba4d0dfd8983dd551b5648232dcaea6b7bee"
    assert commits[0]["message"] == "mcp_tools: default pdsx reads to phi's repo"
    branches = await server.list_branches(REPO_DID)
    assert branches[0]["name"] == "main"

    git = [q for q in world.requests if "/org.tangled.git." in q.url.path]
    assert {q.url.host for q in git} == {KNOT}
    assert {q.url.params["repo"] for q in git} == {REPO_DID}
    [log] = [q for q in git if q.url.path.endswith("listCommits")]
    assert log.url.params["ref"] == "main"  # listCommits requires a ref


async def test_read_file_missing_path_is_a_404(world: World):
    world.routes[(KNOT, "org.tangled.git.getBlob")] = lambda _: httpx.Response(
        404, json={"error": "FileNotFound", "message": "file not found"}
    )
    with pytest.raises(bobbin.BobbinError) as err:
        await server.read_file(REPO_DID, path="nope.md")
    assert isinstance(err.value, bobbin.BobbinError) and err.value.status == 404


async def test_compare_summarizes_the_diff(world: World):
    result = await server.compare(REPO_DID, "3804117", "6f33ba4")
    assert result["stats"] == {"insertions": 155, "deletions": 25, "filesChanged": 12}
    assert result["files"][0] == {
        "old_path": "CHANGELOG.md",
        "new_path": "CHANGELOG.md",
    }


async def test_list_pipelines_asks_the_repos_spindle(world: World):
    world.routes[("spindle.zzstoatzz.io", "org.tangled.ci.queryPipelines")] = fixture(
        "pipelines"
    )
    [latest, *_] = await server.list_pipelines(REPO_DID, limit=2)
    assert latest["workflows"] == [{"name": "deploy.yml", "status": "success"}]
    assert world.hosts("queryPipelines") == {"spindle.zzstoatzz.io"}


# --- tickets -----------------------------------------------------------------


async def test_list_issues_reads_ticket_markup(world: World):
    [first, *_] = await server.list_issues(REPO_DID)
    assert first["number"] == 2
    assert first["title"].startswith("policy: add thread-fit check")
    assert first["state"] == "open"
    assert first["author"] == "did:plc:65sucjiel52gefhcdcypynsr"
    [listed] = [q for q in world.requests if "listIssues" in q.url.path]
    assert listed.url.params["subject"] == REPO_DID


async def test_list_pulls_carries_the_target_branch(world: World):
    [newest, *_] = await server.list_pulls(REPO_DID)
    assert (newest["number"], newest["state"], newest["target_branch"]) == (
        26,
        "completed",
        "main",
    )


@pytest.mark.parametrize(
    "ref", ["zzstoatzz.io/bot#25", f"at://{REPO_DID}/org.tangled.track.ticket/25"]
)
async def test_ticket_references(world: World, monkeypatch, ref: str):
    monkeypatch.setattr(bobbin, "resolve_handle", AsyncMock(return_value=OWNER_DID))
    r, number = await server._ticket(ref)
    assert (r.repo_did, number) == (REPO_DID, "25")


async def test_legacy_issue_uri_points_at_the_new_lists():
    with pytest.raises(ValueError, match="list_issues"):
        await server._ticket("at://did:plc:author/sh.tangled.repo.issue/3mabc")


# --- pulls -------------------------------------------------------------------


def patch_record(cid: str, ticket: str, base: str, head: str, at: str) -> dict:
    return {
        "uri": f"at://{REPO_DID}/org.tangled.review.patch/{cid}",
        "cid": cid,
        "value": {
            "$type": "org.tangled.review.patch",
            "ticket": ticket,
            "base": {"oid": base},
            "head": {"oid": head},
            "createdAt": at,
        },
    }


async def test_get_pull_names_its_latest_round(world: World):
    world.routes[(KNOT, "com.atproto.repo.listRecords")] = {
        "records": [
            patch_record("round-two", "26", "b1", "h2", "2026-11-02T00:00:00Z"),
            patch_record("round-one", "26", "b1", "h1", "2026-11-01T00:00:00Z"),
            patch_record("other", "9", "x", "y", "2026-11-03T00:00:00Z"),
        ]
    }
    pull = await server.get_pull(TICKET_26)
    assert (pull["rounds"], pull["cid"], pull["base"], pull["head"]) == (
        2,
        "round-two",
        "b1",
        "h2",
    )


def _legacy_world(world: World, legacy: list[dict]) -> None:
    gardener = "did:plc:7vx7exykq2zfxjxxejovrymi"
    view = fixture("ticket_view")

    def listed(request: httpx.Request) -> httpx.Response:
        if request.url.params["repo"] == gardener:
            return httpx.Response(200, json={"records": legacy})
        return httpx.Response(200, json={"records": []})

    world.routes[(BOBBIN, "org.tangled.track.getTicketView")] = view
    world.routes[(KNOT, "com.atproto.repo.listRecords")] = listed
    world.routes[("pds.example", "com.atproto.repo.listRecords")] = listed

    def plc(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(gardener):
            return httpx.Response(200, json=did_doc("https://pds.example"))
        return httpx.Response(200, json=did_doc(f"https://{KNOT}"))

    world.routes[("plc.directory", "*")] = plc


def legacy_pull(rkey: str, title: str, repo: str = REPO_DID) -> dict:
    return {
        "uri": f"at://did:plc:7vx7exykq2zfxjxxejovrymi/sh.tangled.repo.pull/{rkey}",
        "cid": f"cid-{rkey}",
        "value": {
            "title": title,
            "target": {"repo": repo, "branch": "main"},
            "rounds": [{"patchBlob": {"ref": {"$link": "blob"}}}],
        },
    }


THREAD_FIT = "policy: thread-fit warn for replies in someone else's thread"


async def test_a_migrated_pull_finds_its_legacy_rounds(world: World):
    _legacy_world(
        world,
        [
            legacy_pull("3mulujsfye7fn", THREAD_FIT),
            legacy_pull("3elsewhere", THREAD_FIT, repo="did:plc:another"),
            legacy_pull("3other", "something else"),
        ],
    )
    pull = await server.get_pull(f"at://{REPO_DID}/org.tangled.track.ticket/25")
    assert pull["cid"] == "cid-3mulujsfye7fn"
    assert pull["legacy_pull"].endswith("/3mulujsfye7fn")


async def test_an_ambiguous_legacy_match_is_no_match(world: World):
    _legacy_world(world, [legacy_pull("3a", THREAD_FIT), legacy_pull("3b", THREAD_FIT)])
    with pytest.raises(ValueError, match="no patch rounds"):
        await server.get_pull(f"at://{REPO_DID}/org.tangled.track.ticket/25")


async def test_get_pull_patch_renders_the_round_from_both_sides(world: World):
    world.routes[(KNOT, "com.atproto.repo.listRecords")] = {
        "records": [patch_record("round", "26", "base", "head", "2026-11-01T00:00:00Z")]
    }
    world.routes[(KNOT, "org.tangled.git.getDiff")] = {
        "diffs": [
            {
                "lhsSrc": {"path": "phi.md", "isBinary": False},
                "rhsSrc": {"path": "phi.md", "isBinary": False},
                "hunks": [],
                "hasSyntacticChanges": True,
            }
        ]
    }
    content = {"base": "one\ntwo\n", "head": "one\nthree\n"}
    world.routes[(KNOT, "org.tangled.git.getBlob")] = lambda request: httpx.Response(
        200, content=content[request.url.params["ref"]].encode()
    )
    patch = await server.get_pull_patch(TICKET_26, expected_cid="round")
    assert "Subject: [PATCH] policy: thread-fit warn" in patch
    assert "-two\n+three\n" in patch
    with pytest.raises(ValueError, match="Pull changed"):
        await server.get_pull_patch(TICKET_26, expected_cid="older-round")


async def test_get_pull_file_reads_the_rounds_head(world: World):
    world.routes[(KNOT, "com.atproto.repo.listRecords")] = {
        "records": [patch_record("round", "26", "base", "head", "2026-11-01T00:00:00Z")]
    }
    world.routes[(KNOT, "org.tangled.git.getBlob")] = lambda request: httpx.Response(
        200, content=f"at {request.url.params['ref']}".encode()
    )
    assert await server.get_pull_file(TICKET_26, "phi.md") == "at head"


# --- writes go to the knot as the caller ---------------------------------------


class Knot:
    """captures writes; answers like knot-server does"""

    def __init__(self, world: World) -> None:
        self.writes: list[dict[str, Any]] = []
        self.minted: list[dict[str, str]] = []
        self.attested: list[dict[str, Any]] = []
        world.routes[(KNOT, "com.atproto.repo.createRecord")] = self.write
        world.routes[(KNOT, "com.atproto.repo.putRecord")] = self.write
        world.routes[(KNOT, "com.atproto.repo.deleteRecord")] = self.write
        world.routes[(KNOT, "org.tangled.review.submitPatch")] = self.write
        world.routes[(KNOT, "com.atproto.repo.getRecord")] = self.get
        world.routes[("pds.example", "com.atproto.server.getServiceAuth")] = self.mint
        world.routes[("pds.example", "com.atproto.repo.putRecord")] = self.attest

    def write(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        body["_nsid"] = request.url.path.rsplit("/", 1)[-1]
        body["_auth"] = request.headers["authorization"]
        self.writes.append(body)
        return httpx.Response(
            200,
            json={
                "uri": f"at://{REPO_DID}/{body.get('collection', records.PATCH)}/27",
                "cid": "written",
                "x-tngl-change": "change-oid",
            },
        )

    def get(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "uri": TICKET_26,
                "cid": "current",
                "value": {
                    "$type": "org.tangled.track.ticket",
                    "title": {"$type": records.INLINE, "text": "t"},
                    "state": "open",
                    "createdAt": "2026-10-09T06:34:13Z",
                    "x-tngl-editor": "did:plc:someone",
                },
            },
        )

    def mint(self, request: httpx.Request) -> httpx.Response:
        self.minted.append(dict(request.url.params))
        return httpx.Response(
            200, json={"token": f"token-for-{request.url.params['lxm']}"}
        )

    def attest(self, request: httpx.Request) -> httpx.Response:
        self.attested.append(json.loads(request.content))
        return httpx.Response(200, json={"uri": "at://me/x/y", "cid": "c"})


@pytest.fixture
def knot(world: World, monkeypatch: pytest.MonkeyPatch) -> Knot:
    k = Knot(world)

    async def login() -> records.Session:
        return records.Session(
            client=bobbin._client, did="did:plc:me", pds="https://pds.example"
        )

    monkeypatch.setattr(records, "login", login)
    return k


async def test_create_issue_writes_through_the_knot_and_attests(
    world: World, knot: Knot
):
    result = await server.create_issue(REPO_DID, "a title", body="a body")
    [write] = knot.writes
    assert write["_nsid"] == "com.atproto.repo.createRecord"
    assert write["repo"] == REPO_DID
    assert "rkey" not in write  # the knot mints ticket numbers
    assert write["record"]["title"] == {"$type": records.INLINE, "text": "a title"}
    assert write["record"]["body"] == {"$type": records.MARKDOWN, "text": "a body"}
    assert write["record"]["state"] == "open"
    assert write["_auth"] == "Bearer token-for-com.atproto.repo.createRecord"
    assert knot.minted == [{"aud": REPO_DID, "lxm": "com.atproto.repo.createRecord"}]
    [attestation] = knot.attested
    assert attestation["collection"] == records.ATTESTATION
    assert attestation["record"]["subject"] == {"uri": result["uri"], "cid": "written"}
    assert attestation["record"]["change"] == "change-oid"
    assert result["url"].endswith("/issues/27")


async def test_a_failed_attestation_is_reported_not_raised(world: World, knot: Knot):
    world.routes[("pds.example", "com.atproto.repo.putRecord")] = lambda _: (
        httpx.Response(500, json={"error": "InternalServerError", "message": "down"})
    )
    result = await server.create_issue(REPO_DID, "a title")
    assert result["cid"] == "written"
    assert "down" in result["attestation_error"]


async def test_set_issue_state_swaps_the_current_version(world: World, knot: Knot):
    await server.set_issue_state(TICKET_26, "closed")
    [write] = knot.writes
    assert write["_nsid"] == "com.atproto.repo.putRecord"
    assert (write["rkey"], write["swapRecord"]) == ("26", "current")
    assert write["record"]["state"] == "closed"
    assert "x-tngl-editor" not in write["record"]  # the knot stamps it


async def test_comment_on_pull_points_at_the_latest_round(world: World, knot: Knot):
    world.routes[(KNOT, "com.atproto.repo.listRecords")] = {
        "records": [patch_record("round", "26", "b", "h", "2026-11-01T00:00:00Z")]
    }
    await server.comment_on_pull(TICKET_26, "VERDICT: approve", expected_cid="round")
    [write] = knot.writes
    assert write["collection"] == records.COMMENT
    assert write["record"]["subject"] == {
        "uri": f"at://{REPO_DID}/org.tangled.review.patch/round",
        "cid": "round",
    }
    assert write["record"]["body"]["text"] == "VERDICT: approve"


@pytest.fixture
def pushes(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    from tangled_mcp import git

    calls: list[dict[str, Any]] = []

    async def fake(url, token, from_branch, to_branch, edits, message, author):
        calls.append({"url": url, "token": token, "from": from_branch, "to": to_branch})
        return git.Pushed(parent=f"tip-of-{from_branch}", head="new-head")

    monkeypatch.setattr(git, "commit_and_push", fake)
    monkeypatch.setattr(
        records,
        "resolve_credentials",
        lambda: records.Credentials(handle="phi.zzstoatzz.io", password="pw"),
    )
    return calls


async def test_create_pull_pushes_a_branch_then_opens_round_zero(
    world: World, knot: Knot, pushes: list
):
    edit = server.Edit(path="personalities/phi.md", content="new\n")
    result = await server.create_pull(REPO_DID, "Tighten the voice", edits=[edit])
    [push] = pushes
    assert push["url"] == f"https://{KNOT}/{REPO_DID}"
    assert push["from"] == "main"
    assert push["to"].startswith("phi/tighten-the-voice-")
    assert push["token"] == "token-for-org.tangled.git.receivePack"
    assert {"aud": f"did:web:{KNOT}", "lxm": "org.tangled.git.receivePack"} in (
        knot.minted
    )
    ticket, round_zero = knot.writes
    assert ticket["record"]["targetBranch"] == "main"
    assert round_zero["_nsid"] == "org.tangled.review.submitPatch"
    assert round_zero["patch"] == {
        "ticket": "27",
        "base": {"oid": "tip-of-main"},
        "head": {"oid": "new-head"},
        "sourceRepo": REPO_DID,
        "sourceBranch": push["to"],
    }
    assert result["url"].endswith("/pulls/27")


async def test_a_refused_round_takes_the_ticket_back(
    world: World, knot: Knot, pushes: list
):
    world.routes[(KNOT, "org.tangled.review.submitPatch")] = lambda _: (
        httpx.Response(400, json={"error": "InvalidRequest", "message": "no head"})
    )
    with pytest.raises(RuntimeError, match="no head"):
        await server.create_pull(
            REPO_DID, "t", edits=[server.Edit(path="a.md", content="x")]
        )
    ticket, erase = knot.writes
    assert erase["_nsid"] == "com.atproto.repo.deleteRecord"
    assert (erase["rkey"], erase["swapRecord"]) == ("27", "written")


def _own_pull(world: World, author: str) -> None:
    round_zero = patch_record("r0", "26", "base-oid", "h0", "2026-11-01T00:00:00Z")
    round_zero["value"]["source"] = {"repo": REPO_DID, "branch": "phi/change"}
    world.routes[(KNOT, "com.atproto.repo.listRecords")] = {"records": [round_zero]}
    view = fixture("ticket_view")
    view["author"] = {"did": author, "handle": "phi.zzstoatzz.io"}
    world.routes[(BOBBIN, "org.tangled.track.getTicketView")] = view


async def test_update_pull_stacks_a_round_on_its_branch(
    world: World, knot: Knot, pushes: list
):
    _own_pull(world, "did:plc:me")
    result = await server.update_pull(
        TICKET_26, edits=[server.Edit(path="a.md", content="y")], note="fix"
    )
    [push] = pushes
    assert (push["from"], push["to"]) == ("phi/change", "phi/change")
    [round_one] = knot.writes
    assert round_one["patch"]["base"] == {"oid": "base-oid"}
    assert round_one["patch"]["head"] == {"oid": "new-head"}
    assert result["round"] == 2


async def test_update_pull_refuses_someone_elses_pull(
    world: World, knot: Knot, pushes: list
):
    _own_pull(world, "did:plc:someone-else")
    with pytest.raises(ValueError, match="your own pull"):
        await server.update_pull(
            TICKET_26, edits=[server.Edit(path="a.md", content="y")]
        )
    assert pushes == [] and knot.writes == []


async def test_stale_review_rejected_before_login(world: World, monkeypatch):
    world.routes[(KNOT, "com.atproto.repo.listRecords")] = {
        "records": [patch_record("new", "26", "b", "h", "2026-11-01T00:00:00Z")]
    }
    login = AsyncMock()
    monkeypatch.setattr(records, "login", login)
    with pytest.raises(ValueError, match="Pull changed"):
        await server.comment_on_pull(TICKET_26, "VERDICT: approve", expected_cid="old")
    login.assert_not_awaited()


async def test_verdict_requires_revision_identity(monkeypatch):
    login = AsyncMock()
    monkeypatch.setattr(records, "login", login)
    with pytest.raises(ValueError, match="require the CID"):
        await server.comment_on_pull(TICKET_26, "VERDICT: approve")
    login.assert_not_awaited()


# --- credentials ---------------------------------------------------------------


def test_tid_shape_and_sortability():
    a, b = tid(), tid()
    assert len(a) == len(b) == 13
    assert a[:10] <= b[:10]  # timestamp prefix is base32-sortable


def test_resolve_credentials_headers_win_and_never_mix(monkeypatch: Any):
    from tangled_mcp.settings import settings

    monkeypatch.setattr(settings, "tangled_handle", "env.handle")
    monkeypatch.setattr(settings, "tangled_password", "env-pass")
    # no headers → env credentials
    monkeypatch.setattr(records, "get_http_headers", lambda: {})
    creds = records.resolve_credentials()
    assert (creds.handle, creds.password) == ("env.handle", "env-pass")

    # header identity is used whole — env password must NOT fill the gap
    monkeypatch.setattr(
        records, "get_http_headers", lambda: {"x-tangled-handle": "phi.handle"}
    )
    creds = records.resolve_credentials()
    assert creds.handle == "phi.handle"
    assert creds.password is None

    # complete header identity
    monkeypatch.setattr(
        records,
        "get_http_headers",
        lambda: {
            "x-tangled-handle": "phi.handle",
            "x-tangled-password": "phi-pass",
        },
    )
    creds = records.resolve_credentials()
    assert (creds.handle, creds.password) == ("phi.handle", "phi-pass")


async def test_discover_pds_routes_by_did_method(monkeypatch: Any):
    requested: list[str] = []

    class FakeResponse:
        def json(self) -> dict[str, Any]:
            return did_doc("https://pds.example")

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None: ...
        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: Any) -> None: ...
        async def get(self, url: str) -> FakeResponse:
            requested.append(url)
            return FakeResponse()

    monkeypatch.setattr(records.httpx, "AsyncClient", FakeClient)

    assert await records.discover_pds("did:plc:abc123") == "https://pds.example"
    assert requested[-1] == "https://plc.directory/did:plc:abc123"

    assert await records.discover_pds("did:web:pds.example") == "https://pds.example"
    assert requested[-1] == "https://pds.example/.well-known/did.json"
