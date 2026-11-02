# tangled's public XRPC surfaces

checked live 2026-11-02, after tangled's move to `org.tangled.*` lexicons
(tangled core `d15cbd9da`, 2026-10-30). lexicons and placement rules live in
`tangled.org/core`: `lexicons/org/tangled/`, `docs/src/content/docs/reference/records.md`,
`docs/src/content/docs/api/{bobbin,knot,spindle}.md`.

## where each read goes

| what | host | methods |
|---|---|---|
| repo lookup | bobbin `api.tangled.org` | `org.tangled.repo.getRepoByName?owner=<DID>&name=` (a handle fails the regex), `getRepoByRepoDid?repoDid=`; both return `{uri: <repoDid>/org.tangled.repo.manifest/self, value, knot, defaultBranch}` |
| repo lists | bobbin | `org.tangled.repo.listRepos?subject=<owner DID>`, `listIssues` / `listPulls?subject=<repo DID>` (items carry `author`, `state`, `commentCount`, `value`) |
| ticket | bobbin | `org.tangled.track.getTicketView?uri=` |
| search | bobbin | `org.tangled.search.query?q=` |
| git | the repo's knot | `org.tangled.git.getTree`, `getBlob` (raw bytes, 404 `FileNotFound`), `listCommits` (`ref` required), `listBranches`, `listTags`, `listLanguages`, `getDiff?base=&head=` (line numbers only, no text) — all `?repo=<repo DID>`. bobbin 404s these |
| records | the repo's knot | `com.atproto.repo.getRecord` / `listRecords` for tickets, patches, comments, label definitions |
| CI | the repo's spindle | `org.tangled.ci.queryPipelines?repo=<repo DID>` on the host of the manifest's `spindle` did:web |

the `org.tangled.temp.git.*` methods (formatPatch, getMergeBase) 404 on knot1.

## records

- tickets: `org.tangled.track.ticket`, rkey = the ticket number the knot mints.
  `title` is `markup.markdown#inline`, `body` is `markup.markdown`, `state` is
  open/closed/completed. a ticket with `targetBranch` is a pull
- patches: `org.tangled.review.patch`, rkey = its own cid, `{ticket: <number>,
  base, head, source}`. one per round, immutable
- comments: `org.tangled.feed.comment`, `{subject: strongRef, body: markdown}`.
  the subject can be a ticket or a patch

## writes

POST `https://<knot>/xrpc/com.atproto.repo.{createRecord,putRecord,deleteRecord}`
with `Authorization: Bearer <service JWT>`, minted by the caller's PDS
(`com.atproto.server.getServiceAuth?aud=<repo DID>&lxm=<method>`). the knot mints
ticket and comment rkeys (passing one is rejected), requires `swapRecord` on
put/delete, stamps `x-tngl-editor`, and returns `x-tngl-change` in the body for
the caller's `org.tangled.graph.attestation`. a ticket opens `open`; state
changes are a putRecord by the author or a maintainer.

git push takes the same kind of token (`lxm` `org.tangled.git.receivePack`) as a
Bearer or Basic password. opening a pull is a ticket plus
`org.tangled.review.submitPatch` naming a pushed source branch.
