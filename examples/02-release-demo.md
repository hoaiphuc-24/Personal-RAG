# DEMO — Software Release Process

This is a fictional example, not your company's current process.

## Release Requirements
Every pull request must have at least one reviewer. Automated checks
must pass before merging. Do not put secrets or customer data in the repository.

## Release Steps
1. The release owner defines the scope and writes release notes.
2. Run automated checks and acceptance tests in staging.
3. Back up the database when changing the schema.
4. The technical owner approves the release.
5. Deploy and monitor errors during the first 30 minutes.

## Rollback
If the error rate exceeds the threshold agreed in the release plan,
the on-call operator rolls back to the most recent stable version and notifies the project team.
Prepare the rollback plan before deployment.
