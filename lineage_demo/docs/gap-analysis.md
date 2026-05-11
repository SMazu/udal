# Gap Analysis

This file captures the remaining production-release gaps after the current
handoff refactor.

## Closed In This Handoff

- Core package isolation: demo config, engine setup, execution helpers, and CSV
  fixtures were moved out of `src/ibis_unified_lineage`.
- Wheel contents: the wheel no longer force-includes example fixtures.
- Package metadata: renamed the distribution to `ibis-unified-lineage`, added
  readme metadata, keywords, authors, and Python classifiers.
- Test coverage: added a public package surface test and kept installed-wheel
  matrix checks for Python 3.10-3.14.
- Typing marker: added `py.typed` so downstream type checkers can consume the
  package annotations.
- Documentation: added agent handoff notes, architecture docs, release docs,
  and a draft Trusted Publishing workflow.

## Remaining Owner Decisions

- License: the project owner must choose a license before public release.
- PyPI name: the next agent must verify whether `ibis-unified-lineage` is
  available on PyPI and TestPyPI.
- Repository URL: add `project.urls` once the standalone repository exists.
- Maintainers: replace the generic author with real maintainer names or an
  organization.
- Release status: keep `Development Status :: 3 - Alpha` unless the owner wants
  a stronger stability claim.

## Future Engineering Milestones

- Add static type checking and a formatter/linter workflow once style choices
  are agreed.
- Add OpenLineage/DataHub emitters on top of `LineageGraph`.
- Add property-based Ibis expression tests for more operation combinations.
- Add policy switches for whether filter/join/group context should propagate to
  all projected outputs or only affected outputs.
- Add richer SQLGlot source expansion for nested CTEs and dialect-specific SQL.
- Harden the service image with a non-root runtime user if it becomes more than
  an integration-test artifact.
