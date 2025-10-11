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

# push to both tangled and github
push message:
    git add .
    git commit -m "{{message}}"
    git push origin main
