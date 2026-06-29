# TaxSentry Prepublish Checklist

Use this checklist before publishing a new package version.

## Required checks
- [ ] `npm run test`
- [ ] `npm run lint`
- [ ] `npm run pack:smoke`
- [ ] `npm publish --dry-run`

## Packaging safety checks
- [ ] Tarball does not include `.env`, audit reports, worklogs, scratch files, or personal paths
- [ ] Tarball includes `bin/`, `src/`, `taxsentry-core/pyproject.toml`, `taxsentry-core/requirements.txt`, `README.md`, and `LICENSE`
- [ ] `.env.example` inside the tarball contains only placeholders, not secrets or personal emails
- [ ] Release note / Obsidian roadmap updated with the verified scope

## Release rule
Only publish when all required checks are green and the tarball inspection is clean.