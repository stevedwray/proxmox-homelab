#!/usr/bin/env python3
from client import NetBoxClient

nb = NetBoxClient()


def find_ip(ip):
    for candidate in (ip, ip + "/24"):
        res = nb.live_get("/ipam/ip-addresses/", address=candidate)
        if res.get("count", 0) > 0:
            obj = res["results"][0]
            print(f"IP {ip} -> id={obj.get('id')} address={obj.get('address')} assigned_obj_type={obj.get('assigned_object_type')} assigned_obj_id={obj.get('assigned_object_id')}")
            return
    print(f"IP {ip} -> NOT_FOUND")


def find_vm(vmname):
    res = nb.live_get("/virtualization/virtual-machines/", name=vmname)
    if res.get("count", 0) > 0:
        vm = res["results"][0]
        primary = vm.get('primary_ip4') or vm.get('primary_ip')
        print(f"VM {vmname} -> id={vm.get('id')} name={vm.get('name')} primary_ip={primary}")
        return
    print(f"VM {vmname} -> NOT_FOUND")


if __name__ == '__main__':
    find_ip('192.168.20.20')
    find_ip('192.168.1.53')
    find_vm('portainer-stack@pve-test')
    find_vm('docker-socket-proxy-test@pve-test')
