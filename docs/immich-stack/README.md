# immich-stack (superseded)

**Superseded 2026-08-25 by [docs/media-stack-lab/](../media-stack-lab/README.md).**
The operator's actual goal turned out to be broader than "add Immich" --
a full replacement for legacy `media-stack`, with Jellyfin, watch-history
migration, and Authentik SSO for both apps. The zone (`media_seg`, VLAN 80)
and storage (NFS) decisions made here carried forward unchanged; everything
else is rewritten there. Kept as history, not a live plan -- don't build
from this file.
