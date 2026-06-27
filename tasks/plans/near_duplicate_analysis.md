# C3: Near-Duplicate Service Analysis — Jaccard Import Similarity

**Method:** AST-parsed imports per service, Jaccard similarity of top-level import names.
**Caveat:** Most high-similarity pairs share common stdlib imports (`typing`, `logging`, `abc`, `pathlib`, `enum`). Top-level import name (e.g. `typing`, `weebot`) doesn't distinguish between `from typing import Optional` and `from weebot.domain import Entity`.

## Verdict: No Safe Merge Candidates Found

The initial scan produced many false positives (Jaccard = 1.00 for entirely unrelated
services with identical stdlib import sets). A refined scan would need to:

1. Filter to **`weebot.` prefix imports only** (ignore stdlib, third-party)
2. Compare **import structure** (class relationships, method signatures)
3. Verify **semantic overlap** by reading the actual service logic

**Recommendation: Skip C3.** The risk of incorrectly merging functionally distinct
services outweighs the marginal benefit of removing 6–10 files. Focus effort on C4
(domain-logic relocation) which is safer and directly improves architectural layering.
