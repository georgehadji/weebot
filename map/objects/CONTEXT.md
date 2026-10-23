# objects/

One card per noun, cluster folders by how an editor asks. Cards are created from `../_templates/object.md` and only when someone needs them; until then the noun is a stub line in `_index.md`.

Clusters: `domain/`, `application/`, `infrastructure/`, `interfaces/`, `core/`, `tools/` (folders created with the first card in each).

Inputs for a card: the source file cited in `_index.md`, `ARCHITECTURE.md` for ADRs, `.importlinter` for layer rules.
Output: one card, `status: stub` until every claim is cited and re-read against source.
