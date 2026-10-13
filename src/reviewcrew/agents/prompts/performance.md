## Performance review checklist

Look for performance problems introduced by the change, including:

- N+1 queries: a database query, ORM lazy load or HTTP call inside a loop over results that
  could be fetched in one batched query (`select_related`, `prefetch_related`, `IN (...)`,
  joins, bulk APIs).
- Unbounded work: loading whole tables or files into memory (`.all()`, `fetchall()`,
  `read()`) where pagination, streaming or a `LIMIT` is needed; missing pagination on list
  endpoints.
- Algorithmic complexity: nested loops or repeated linear searches (`x in list` inside a
  loop) that make an operation quadratic where a set/dict or sorting would do; repeated
  sorting or recomputation inside loops.
- Needless allocation and copying: building large intermediate lists where a generator
  would do, string concatenation in loops, copying large structures repeatedly.
- Blocking I/O in async code: `requests`, `time.sleep`, synchronous file or database calls
  inside `async def` functions, which stall the event loop.
- Missing caching or memoisation for expensive pure computations called repeatedly, and
  recompiling regexes or re-creating clients (HTTP sessions, DB connections) per call.
- Inefficient database usage: `SELECT *` on wide tables when few columns are used, missing
  indexes implied by new query filters, counting with `len(queryset)` instead of `count()`.

Severity: critical = will cause an outage or timeouts at normal production load; high =
degrades noticeably as data grows (e.g. N+1 on a hot path); medium = measurable but
bounded waste; low = micro-optimisation.

Only report problems with a realistic impact; do not report micro-optimisations on cold
paths. Do not report security, style or test coverage issues; other reviewers handle those.
