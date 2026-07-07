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

# push main to both remotes (tangled origin + github mirror → fastmcp cloud deploy)
push:
    git push origin main
    git push https://github.com/zzstoatzz/tangled-mcp.git main
