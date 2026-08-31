## Summary

<!-- What changed and why. Keep it to one short paragraph. -->

## Type of change

- [ ] Bugfix
- [ ] Feature (module scope)
- [ ] Database migration
- [ ] Frontend
- [ ] Documentation
- [ ] Refactor / chore

## Checklist

- [ ] `ruff check app tests cli.py` passes
- [ ] `python -m pytest tests/` passes (note the final count)
- [ ] Frontend touched: `eslint`, `tsc`, `npm run build` all pass
- [ ] Migration touched: verified `alembic upgrade head` on a fresh database
- [ ] Money amounts stay `Decimal` / JSON strings — no floats
- [ ] `README.md` updated — or commit message contains `[skip-readme]`
- [ ] No secrets or credentials committed
- [ ] Internal PRD / SDLC documents are NOT included (repo docs hygiene)
