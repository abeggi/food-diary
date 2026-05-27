# AGENTS.md

This repo is simple: single-file FastAPI backend (`main.py`), vanilla HTML/CSS/JS frontend, SQLite database. See `CLAUDE.md` for operational details (run commands, env vars, architecture, auth flow, DB schema, frontend conventions).

What `CLAUDE.md` does not cover:

- **No tests.** Zero test files or test framework. Do not search for or run tests.
- **No linter, formatter, or typechecker.** No verification commands exist.
- **No build step.** No `package.json`, no bundler. Frontend is served as-is.
- **Sync both HTML files.** CSS custom properties, fonts, and category colors are defined in `:root` in both `static/index.html` and `static/settings.html`. When modifying theme, update both identically.
- **No auth.** Firebase and multi-tenancy have been removed. Auth is handled externally by the reverse proxy. The single user (`abeggi`) is always admin.
- **`static/firebase-config.js` no longer exists.** It and its example were deleted. Do not create or reference it.
- **`CLAUDE.md` auth section is outdated.** It still describes the old Firebase flow — ignore that section.
