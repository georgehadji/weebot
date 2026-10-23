# Schema: closed node types

Only these types exist in `map/`. Add a type only after three independent cases need it.

| type | folder | template |
|---|---|---|
| object | `objects/<cluster>/` | `_templates/object.md` |
| process | `processes/` | `_templates/process.md` |

Frontmatter (all cards):

```yaml
---
type: object | process
name: <product name>
code: <type or file name if different>
cluster: domain | application | infrastructure | interfaces | core | tools
universe: live | leftover | ghost
status: stub | verified | stale
verified: <YYYY-MM-DD>   # only with status: verified
commit: <short hash>     # only with status: verified
---
```

`verified` is allowed only with a date, a commit and `path:line` citations on every claim.
