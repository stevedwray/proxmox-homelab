# Task 09: Authentik Discovery

## Type

Development, read-only

## Objective

Query Authentik and map manifest auth intent to current providers,
applications, and outposts without writes.

## Files

- `terraform/lxc/discover-authentik-edge.py`
- tests with mocked API responses

## Preconditions

- Task 05 complete.
- Authentik is healthy for live use.
- Automation token is available through `./with-secrets`.

## Operations

1. Validate manifests.
2. Query applications, providers, and outposts.
3. Classify each manifest route as matching, missing, differing, unmanaged, or
   ambiguous.
4. Include stable object identifiers for the later reconciler.

## Postconditions

- Discovery sends no write methods.
- Missing token fails with an actionable message.

## Validation

- Mocked API tests prove read-only behavior and expected classifications.

## Stop Conditions

- Stop if existing object names cannot be mapped safely to stack-owned names.
