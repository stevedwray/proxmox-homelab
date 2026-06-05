#!/usr/bin/env python3
from client import NetBoxClient
nb=NetBoxClient()

for iface_id in (23, 40):
    res = nb.live_get('/virtualization/interfaces/', id=iface_id)
    if res.get('count',0) > 0:
        iface = res['results'][0]
        vm = iface.get('virtual_machine')
        print(f"iface id={iface_id} -> name={iface.get('name')} vm_ref={vm}")
    else:
        print(f"iface id={iface_id} -> NOT_FOUND")
