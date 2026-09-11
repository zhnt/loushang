# <Scope> Glossary

> Template: keep a short local glossary in a scope README when sufficient.
> Create a separate glossary for substantial reused vocabulary. Keep only
> relevant entry fields and remove these instructions when publishing.

## Status And Ownership

- Scope: `<owning scope>`
- Authority: normative — vocabulary definitions
- Design status: draft
- Implementation status: not-applicable
- Owner: `<vocabulary owner>`
- Inherits: `<parent/global vocabulary references>`

## <Canonical Term>

Define the term's meaning within its owning scope. Distinguish it from commonly
confused concepts; use a short example only when it clarifies that distinction.

- Canonical spelling and qualified name: ...
- Owning scope: ...
- Allowed aliases / translations: ...
- Deprecated names and replacement: ...
- Related concepts / canonical contract: ...

Link observable behavior, ownership rules and implementation evidence to their
canonical artifacts. Do not hide requirements, decisions or Current status in
the definition. A translated entry maps to the normative source and does not
independently change its meaning.

## Shared Index Pattern

When routing several existing glossaries, use a concise index in place of
duplicated definitions:

| Canonical term | Owning scope | Canonical definition link | Alias / translation / deprecated-name routing |
| --- | --- | --- | --- |
| ... | ... | ... | ... |

The index routes meaning; the linked entry owns it. A semantic change updates
the definition, consuming contracts and language mappings together under the
normal decision rules. A different local meaning requires a qualified term.
