# Fixture Notes

This directory is reserved for Task 01 fixture files.

Task 01 should add:

- valid manifests for all six current browser services
- invalid manifests for validator failure cases
- expected error catalog

The examples below are illustrative only and are not the final contract.

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: portainer-edge
  stack: portainer-stack
spec:
  routes:
    - name: portainer
      host: portainer.lab.gibbsgreatly.xyz
      backend:
        type: url
        url: http://10.57.1.20:9000
      dns:
        enabled: true
        target: 10.57.2.10
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: forwardAuth
```

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: traefik-dashboard-edge
  stack: proxy-stack
spec:
  routes:
    - name: traefik-dashboard
      host: traefik.lab.gibbsgreatly.xyz
      backend:
        type: traefikService
        service: api@internal
      dns:
        enabled: true
        target: 10.57.2.10
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: forwardAuth
```
