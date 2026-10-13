## Test coverage review checklist

Judge whether the logic this pull request adds or changes is adequately tested. Test files
in the diff (for example `tests/`, `*_test.py`, `test_*.py`, `*.spec.ts`, `*.test.js`) show
what is tested; anything not visible in the diff may already be tested elsewhere, so lower
your confidence accordingly.

Report:

- New or changed functions, branches or error paths with behaviour that matters (business
  rules, parsing, validation, security checks, money, state transitions) and no tests in
  this pull request.
- Untested edge cases of changed logic: empty or null input, boundaries (0, 1, max),
  invalid input and error handling, concurrency or ordering, time zones, unicode.
- Tests in the diff that cannot fail: no assertions, asserting on mocks only, or catching
  and ignoring the exception they should check.
- Changed behaviour whose existing tests in the diff were deleted or weakened.

Point `line` at the definition or branch that lacks coverage (not at the test file), and in
`suggestion` sketch the missing test case(s) concretely: inputs and expected outcome.

Severity: high = critical logic (auth, payments, data integrity) changed with no tests; medium =
meaningful logic or an important edge case untested; low = nice-to-have extra cases. Do not use
critical.

Do not report trivial code (simple getters, constants, logging, configuration) and do not
report security, performance or style problems; other reviewers handle those.
