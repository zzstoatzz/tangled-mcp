# setup project - sync dependencies and install pre-commit hooks
setup:
    uv sync
    uv run pre-commit install

# run tests
test:
    uv run pytest tests/ -v

# run pre-commit checks
check:
    uv run pre-commit run --all-files

# end-to-end pull request tests: open + verify + close real PRs on tangled
# (needs TANGLED_HANDLE / TANGLED_PASSWORD)
e2e:
    uv run pytest tests/ -m e2e -v --override-ini="addopts="
