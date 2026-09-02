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

# push main; tangled CI deploys the hosted server from the pushed source (.tangled/workflows/deploy.yml)
push:
    git push origin main
