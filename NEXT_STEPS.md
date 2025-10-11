# next steps

## critical fixes

### 1. label validation must fail loudly

**problem:** when users specify labels that don't exist in the repo's subscribed label definitions, they're silently ignored. no error, no warning, just nothing happens.

**current behavior:**
```python
create_repo_issue(repo="owner/repo", labels=["demo", "nonexistent"])
# -> creates issue with NO labels, returns success
```

**what should happen:**
```python
create_repo_issue(repo="owner/repo", labels=["demo", "nonexistent"])
# -> raises ValueError:
#    "invalid labels: ['demo', 'nonexistent']
#     available labels for this repo: ['wontfix', 'duplicate', 'good-first-issue', ...]"
```

**fix locations:**
- `src/tangled_mcp/_tangled/_issues.py:_apply_labels()` - validate before applying
- add `validate_labels()` helper that checks against repo's subscribed labels
- fail fast with actionable error message listing available labels

### 2. list_repo_issues should include label information

**problem:** `list_repo_issues` returns issues but doesn't include their labels. labels are stored separately in `sh.tangled.label.op` records and need to be fetched and correlated.

**impact:** users can't see what labels an issue has without manually querying label ops or checking the UI.

**fix:**
- add `labels: list[str]` field to `IssueInfo` model
- in `list_repo_issues`, fetch label ops and correlate with issues
- return label names (not URIs) for better UX

### 3. fix pydantic field warning

**warning:**
```
UnsupportedFieldAttributeWarning: The 'default' attribute with value None was provided
to the `Field()` function, which has no effect in the context it was used.
```

**likely cause:** somewhere we're using `Field(default=None)` in an `Annotated` type or union context where it doesn't make sense.

**fix:** audit all `Field()` uses and remove invalid `default=None` declarations.

## enhancements

### 4. better error messages for repo resolution failures

when a repo doesn't exist or handle can't be resolved, give users clear next steps:
- is the repo name spelled correctly?
- does the repo exist on tangled.org?
- do you have access to it?

### 5. add label listing tool

users need to know what labels are available for a repo before they can use them.

**new tool:**
```python
list_repo_labels(repo: str) -> list[str]
# returns: ["wontfix", "duplicate", "good-first-issue", ...]
```

### 6. pagination cursor handling

currently returning raw cursor strings. consider:
- documenting cursor format
- providing helper for "has more pages" checking
- clear examples in docstrings

## completed improvements (this session)

### ✅ types architecture refactored
- moved from single `types.py` to `types/` directory
- separated concerns: `_common.py`, `_branches.py`, `_issues.py`
- public API in `__init__.py`
- parsing logic moved into types via `.from_api_response()` class methods

### ✅ proper validation with annotated types
- `RepoIdentifier = Annotated[str, AfterValidator(normalize_repo_identifier)]`
- strips `@` prefix automatically
- validates format before processing

### ✅ clickable URLs instead of AT Protocol internals
- issue operations return `https://tangled.org/@owner/repo/issues/N`
- removed useless `uri` and `cid` from user-facing responses
- URL generation encapsulated in types via `@computed_field`

### ✅ proper typing everywhere
- no more `dict[str, Any]` return types
- pydantic models for all results
- type safety throughout

### ✅ minimal test coverage
- 17 tests covering public contracts
- no implementation details tested
- validates key behaviors: URL generation, validation, parsing

### ✅ demo scripts
- full lifecycle demo
- URL format handling demo
- branch listing demo
- label manipulation demo (revealed silent failure issue)

### ✅ documentation improvements
- MCP client installation instructions in collapsible details
- clear usage examples for multiple clients

## technical debt

### remove unused types
- `RepoInfo`, `PullInfo`, `CreateRepoResult`, `GenericResult` - not used anywhere
- clean up or remove from public API

### consolidate URL generation logic
- `_tangled_issue_url()` helper was created to DRY the URL generation
- good pattern, consider extending to other URL types if needed

### consider lazy evaluation for expensive validations
- repo resolution happens on every tool call
- could cache repo metadata (knot, did) for duration of connection
- tradeoff: freshness vs performance

## priorities

1. **critical:** fix label validation (fails silently)
2. **high:** add labels to list_repo_issues output
3. **medium:** add list_repo_labels tool
4. **medium:** fix pydantic warning
5. **low:** better error messages
6. **low:** clean up unused types
