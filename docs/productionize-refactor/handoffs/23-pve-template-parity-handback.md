# Template Parity Replacement - pve LXC Template

**Status**: ✅ **COMPLETE** — pve production template now matches pve-test reference exactly
**Date**: 2026-05-23
**Operator**: Continued takeover session
**Branch**: work/productionize-06-canary-validation

---

## Original State (Before Replacement)

| Host | Checksum | Size | Path | Modified |
|------|----------|------|------|----------|
| **pve** (production) | `8c283f3dd96c31671d59db30fda7a72ace6b6cb8c86a7428dbfaf353692e5496` | 618M (647,430,741 bytes) | `/storage/template/template/cache/debian-13.1-2-docker-template.tar.gz` | 2026-04-03 02:09:55 UTC |
| **pve-test** (reference) | `39a697a4e7c121b18d8dfd8d70a3845d10f0df04ba0f50a8d3abab3c10bf2250` | 619M (648,585,459 bytes) | `/var/lib/vz/template/cache/debian-13.1-2-docker-template.tar.gz` | 2026-05-17 16:49:01 +1200 |

**Conclusion**: Templates differed by both content (checksum mismatch) and size (1.15MB delta). Decision made to promote pve-test known-good artifact to pve production.

---

## Replacement Procedure

### Step 1: Backup Original pve Template
- **Action**: Created backup of original pve template with timestamp
- **Backup Path**: `/storage/template/template/cache/debian-13.1-2-docker-template.tar.gz.20260523-215218.bak`
- **Backup Size**: 618M (identical to original)
- **Backup Checksum**: `8c283f3dd96c31671d59db30fda7a72ace6b6cb8c86a7428dbfaf353692e5496`
- **Timing**: 2026-05-23 21:52 UTC

### Step 2: Copy pve-test Template to pve
- **Method**: SSH pipe transfer (binary-safe): `ssh root@pve-test cat <file> | ssh root@pve cat > <file>`
- **Source**: `/var/lib/vz/template/cache/debian-13.1-2-docker-template.tar.gz` (pve-test)
- **Destination**: `/storage/template/template/cache/debian-13.1-2-docker-template.tar.gz` (pve production)
- **Transfer Size**: 619M
- **Timing**: Completed 2026-05-23 21:52 UTC

### Step 3: Verification
- **Method**: SHA256 checksum comparison after copy
- **Verification Result**: ✅ **PARITY CONFIRMED**

---

## Final State (After Replacement)

| Host | Checksum | Size | Path | Modified | Status |
|------|----------|------|------|----------|--------|
| **pve** (production) | `39a697a4e7c121b18d8dfd8d70a3845d10f0df04ba0f50a8d3abab3c10bf2250` | 619M (648,585,459 bytes) | `/storage/template/template/cache/debian-13.1-2-docker-template.tar.gz` | 2026-05-23 21:52 UTC | ✅ **MATCHES pve-test** |
| **pve-test** (reference) | `39a697a4e7c121b18d8dfd8d70a3845d10f0df04ba0f50a8d3abab3c10bf2250` | 619M (648,585,459 bytes) | `/var/lib/vz/template/cache/debian-13.1-2-docker-template.tar.gz` | 2026-05-17 16:49:01 +1200 | ✅ **REFERENCE** |

**Conclusion**: Both pve production and pve-test environments now use identical debian-13.1-2-docker-template artifact. Checksum parity: **EXACT**.

---

## Backup Preservation

**Backup Location**: `/storage/template/template/cache/debian-13.1-2-docker-template.tar.gz.20260523-215218.bak`
**Backup Size**: 618M
**Backup Checksum**: `8c283f3dd96c31671d59db30fda7a72ace6b6cb8c86a7428dbfaf353692e5496`
**Retention Policy**: Preserved as fallback; can be manually deleted once pve production template stability is confirmed post-redeploy.

---

## Parity Assertion

```
PARITY CONFIRMED:
  pve (production):    39a697a4e7c121b18d8dfd8d70a3845d10f0df04ba0f50a8d3abab3c10bf2250
  pve-test (reference): 39a697a4e7c121b18d8dfd8d70a3845d10f0df04ba0f50a8d3abab3c10bf2250
  Match: ✅ YES
```

---

## Impact Assessment

**Scope**: Template artifact replacement only. No LXC guest modifications, no network changes, no shared storage outside template cache.

**Risk Level**: **LOW** — Template artifact is read-only after initial deployment; replacement does not affect running or previously deployed containers. Future container deployments will use the newly promoted pve-test template.

**Containers Affected**:
- **None immediately** — Existing LXC guests (created from original pve template) remain unchanged
- **New deployments** — Future LXC containers created on pve will use the pve-test known-good template
- **Redeploy cycles** — Subsequent pve-test→pve promotion cycles will now be faster (no size delta)

---

## Next Steps

1. **Continue pve Infrastructure Redeploy** — Resume Phase 07+ validation work (Section 9 of execution packet)
2. **Monitor Template Stability** — If no new containers fail to deploy within 1 week, consider deleting backup (optional)
3. **Document Final Parity State** — Update [14-pve-parity-pass-01.md](../14-pve-parity-pass-01.md) with this template parity completion as a success milestone

---

## Execution Authorization

- **Task Approval Token**: `pve-template-parity-replacement`
- **Target Environment**: pve (production)
- **Authorization Scope**: Template artifact replacement (read-only mutation)
- **Session**: Continued takeover of pve infra-only teardown test (20260523-204056)
