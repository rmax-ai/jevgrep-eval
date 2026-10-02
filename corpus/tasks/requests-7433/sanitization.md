# Statement sanitization: requests-7433

status: audited-fixture
original_ref: https://github.com/psf/requests/pull/7433
source: public registry title only; no private issue content

## Removed spans

- fix-oriented imperative wording and temporal/revert wording: removed to avoid solution-direction hints.
- issue and pull-request numbers: removed from the task statement.
- filenames, test names, stack traces, patch text, and post-fix symbols: absent from the statement.

## Scans

- gold-only n-grams: performed against gold.patch; no statement-only token is copied from the patch.
- changed paths and introduced symbols: compared against the base tree and patch; no fix-only path or symbol is present.
- PR/commit identifiers: absent from the statement.
- solution-language scan: no implementation language, API recipe, or code token was added.
- base-present identifiers: the public symptom wording was retained where it names behavior already visible in the base.

reviewer_1: round-executor automated checklist passed
reviewer_2: adjudicated at corpus freeze
