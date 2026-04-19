# Task 05: Discover Authentik State

## Type

Development, read-only

## Objective

Create a read-only Authentik discovery and drift report workflow.

## Scope

- Query Authentik API only.
- Do not create, update, or delete Authentik objects.
- Do not modify Traefik or DNS.

## Preconditions

- Authentik is healthy.
- `AUTHENTIK_SUPERUSER_API_TOKEN` or the chosen automation token is available
  through `./with-secrets`.

## Steps

1. Read manifests after Task 02 validation.
2. Query current Authentik applications, providers, and outposts.
3. Map manifest auth modes to required Authentik objects.
4. Report:
   - object exists and matches
   - object exists but differs
   - object missing
   - object unmanaged or ambiguous
5. Include enough object identifiers for a later reconciler to act safely.
6. Add tests using mocked Authentik API responses.

## Validation

- Discovery does not send write methods.
- Missing token fails with an actionable message.
- Forward-auth routes produce expected object requirements.
- `none` and `native` routes do not create Authentik requirements.

## Done When

- Task 06 can implement upsert behavior from a documented object mapping.

## Stop Conditions

- Stop if current Authentik object names cannot be mapped safely to stack-owned
  names. Document the ambiguity instead of guessing.
