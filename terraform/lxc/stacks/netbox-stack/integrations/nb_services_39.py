#!/usr/bin/env python3
from client import NetBoxClient
nb = NetBoxClient()

# Fetch services managed by automation that mention portainer or socket-proxy
services = nb.live_get('/ipam/services/').get('results', [])
for s in services:
    name = s.get('name','')
    if 'portainer' in (name or '').lower() or 'socket-proxy' in (name or '').lower() or 'docker-socket-proxy' in (name or '').lower():
        parent_type = s.get('parent_object_type')
        parent_id = s.get('parent_object_id')
        parent_name = None
        if parent_type == 'virtualization.virtualmachine' and parent_id:
            vmq = nb.live_get('/virtualization/virtual-machines/', id=parent_id)
            if vmq.get('count',0) > 0:
                parent_name = vmq['results'][0].get('name')
        print(f"svc: {name} (id={s.get('id')}) -> parent_type={parent_type} parent_id={parent_id} parent_name={parent_name} tags={[t.get('slug') if isinstance(t, dict) else t for t in s.get('tags',[])]}")
