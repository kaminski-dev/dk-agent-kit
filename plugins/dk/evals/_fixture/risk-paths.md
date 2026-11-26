
## Risk paths

A change that touches one of these paths is risky at any size. Each bullet's backticked globs match the repo-relative path without regard to case, and `*` crosses `/`.

- Migrations and schema: `*migrations/*`, `*schema*`
- Mail: `*mail*`
- CI: `.github/workflows/*`
