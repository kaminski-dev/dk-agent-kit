# Domain docs

- **Glossary**: `GLOSSARY.md` at the repo root. Name things with its terms; a concept it lacks is a gap, not an invitation to invent a synonym.
- **ADRs**: `docs/adr/`, numbered; take the next free number from `ls docs/adr` in the commit that adds one. An ADR earns its file only for a choice that is hard to reverse, surprising without context, and the result of a real trade-off. A change that contradicts an ADR says so in the issue and the PR.

## Glossary change rule

<one of the two, quoted from this repo's existing rule:>

- **Planned on the issue**: a grilling or design session writes its glossary delta into the issue as `_Planned (#N)_` entries; the implementing PR turns them into definitions. `GLOSSARY.md` is not edited before the issue exists.
- **In the PR**: a glossary change lands in `GLOSSARY.md` in the implementing PR, under the section of its area; a conflicting phrase goes under "Flagged ambiguities".
