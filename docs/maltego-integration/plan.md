# maltego-integration — plan

Phase 1 only (see `README.md` for why). Phases 2-6 from `brief.md` are
deliberately left as prose, not step-blocks, until Phase 1's result is known:

- **Phase 2** — generalize into a proper OSINT service layer with caching,
  provenance records, and error handling; extend `cve-mcp-server`'s dormant
  threat-intel integrations (AbuseIPDB/GreyNoise/URLScan/CIRCL PDNS) as part
  of this, not Phase 1.
- **Phase 3** — wire `deep-research-agent` to call the OSINT service via a
  true MCP client (new pattern for that codebase — see `README.md`).
- **Phase 4** — interactive Maltego Desktop transform calling the backend
  over HTTP, with real authentication (neither `cve-mcp-server` nor
  `docs-rag-mcp` currently has app-level auth; the brief requires it even
  for LAN-only — do not copy their no-auth precedent forward here).
- **Phase 5** — investigation persistence (`observations.jsonl` /
  `relationships.jsonl` / `hypotheses.jsonl` per the brief's storage layout).
- **Phase 6** — expanded providers, prioritized by usefulness once Phase 1-3
  show real investigation patterns.

Target: `mcp-utility-stack` (`ai_seg`, pve-tiny, LXC VMID 50011,
`192.168.50.10`) — the existing MCP services' home. Deployment file:
`terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml`.

---

### maltego-01-vendor-source

```yaml
id: maltego-01-vendor-source
title: Add Ansible tasks to copy maltego-mcp source into the build directory
depends_on: []

change: >
  In terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml's second
  play ("Deploy cve-mcp-server compose stack"), add a new `vars` entry
  `maltego_source_dir: "{{ lookup('env', 'MALTEGO_MCP_SOURCE_DIR') | default('/home/steve/git/maltego-mcp', true) }}"`
  and `maltego_build_dir: "{{ mcp_compose_dir }}/maltego-mcp"`, directly
  below the existing `mcp_source_dir`/`mcp_build_dir` vars. Then add three
  tasks after the existing "Copy cve-mcp-server src/ directory..." task
  (before the "Patch copied Dockerfile..." task): (1) a
  `ansible.builtin.file` task named "Create maltego-mcp build directory"
  creating `{{ maltego_build_dir }}` with `state: directory, mode: "0750"`;
  (2) an `ansible.builtin.copy` task named "Copy maltego-mcp source files
  from the controller's local clone" with `loop: [package.json,
  package-lock.json, tsconfig.json, tsup.config.ts, index.ts, cli.ts,
  mcp-bin.ts, mcp-server.ts, README.md, LICENSE]`, `src: "{{
  maltego_source_dir }}/{{ item }}"`, `dest: "{{ maltego_build_dir }}/{{
  item }}"`, `mode: preserve`; (3) an `ansible.builtin.copy` task named
  "Copy maltego-mcp src/ directory from the controller's local clone" with
  `src: "{{ maltego_source_dir }}/src"`, `dest: "{{ maltego_build_dir }}/"`
  (no trailing `/src` on dest — see the comment immediately above the
  equivalent cve-mcp-server task for why), `mode: preserve`.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / ansible-playbook run against pve-tiny -- validation only in this step"
    - "Do not touch the existing cve-mcp-server or docs-rag-mcp tasks"

gates:
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml"
    expect: "exit 0"
    critical: true
  - id: three-new-tasks-present
    cmd: "grep -c 'maltego-mcp' terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml"
    expect: "output >= 5"
    critical: false
```

---

### maltego-02-dockerfile-and-driver

```yaml
id: maltego-02-dockerfile-and-driver
title: Write the maltego-mcp Dockerfile and Phase 1 driver script via Ansible content blocks
depends_on: [maltego-01-vendor-source]

change: >
  In the same play as maltego-01, add two `ansible.builtin.copy` tasks using
  literal `content:` blocks (same style as the existing "Write mcp-utility-
  stack docker-compose.yml" task further down the file), placed after the
  three maltego-01 tasks and before the "Patch copied Dockerfile..." task.
  Task 1, "Write maltego-mcp Dockerfile", writes to
  `{{ maltego_build_dir }}/Dockerfile` with the exact Dockerfile content
  given below. Task 2, "Write maltego-mcp Phase 1 driver script", writes
  to `{{ maltego_build_dir }}/phase1-expand-domain.mjs` with the exact
  script content given below. Both use `mode: "0640"`.

  Dockerfile content (write exactly, do not add a HEALTHCHECK or EXPOSE --
  this image has no HTTP port in Phase 1):

  ```
  # syntax=docker/dockerfile:1
  #
  # maltego-mcp, vendored from https://github.com/lidless-labs/maltego-mcp
  # (MIT license, inspected and pinned at commit cb810042 2026-10-02 --
  # see docs/maltego-integration/README.md). Not pulled through Harbor --
  # same convention as cve-mcp-server's own Dockerfile in this stack
  # (single small image, no second consumer yet).
  #
  # Phase 1 only: this image has no long-running server command. It is
  # invoked per-call via `docker compose run --rm maltego-mcp node
  # phase1-expand-domain.mjs <domain> <outputPath>`, never `docker compose
  # up`. See docs/maltego-integration/plan.md.
  FROM node:20-slim AS builder
  WORKDIR /app
  COPY package.json package-lock.json tsconfig.json tsup.config.ts ./
  COPY index.ts cli.ts mcp-bin.ts mcp-server.ts ./
  COPY src ./src
  RUN npm ci && npm run build

  FROM node:20-slim
  RUN useradd --create-home --shell /usr/sbin/nologin app
  WORKDIR /app
  COPY --from=builder /app/node_modules ./node_modules
  COPY --from=builder /app/dist ./dist
  COPY phase1-expand-domain.mjs ./
  ENV MALTEGO_MCP_OUTPUT_DIR=/home/app/MaltegoGraphs
  RUN mkdir -p /home/app/MaltegoGraphs && chown -R app:app /home/app
  USER app
  ENTRYPOINT ["node"]
  CMD ["dist/mcp-server.js"]
  ```

  phase1-expand-domain.mjs content (write exactly):

  ```javascript
  // Phase 1 driver: domain -> DNS + WHOIS + ASN(per A record) + crt.sh ->
  // .mtgx. Calls maltego-mcp's own exported lookup/graph functions
  // directly -- no MCP stdio protocol involved, see
  // docs/maltego-integration/README.md for why. Usage:
  //   node phase1-expand-domain.mjs <domain> <outputFileName>
  // outputFileName is relative to MALTEGO_MCP_OUTPUT_DIR.
  import { join } from "node:path";
  import { Graph } from "./dist/graph/graph.js";
  import { writeMtgxFile } from "./dist/graph/writer.js";
  import { dnsLookup } from "./dist/lookups/dns.js";
  import { whoisLookup } from "./dist/lookups/whois.js";
  import { asnLookup } from "./dist/lookups/asn.js";
  import { crtshLookup } from "./dist/lookups/crtsh.js";

  const [domain, outputFileName] = process.argv.slice(2);
  if (!domain || !outputFileName) {
    console.error("usage: node phase1-expand-domain.mjs <domain> <outputFileName>");
    process.exit(1);
  }

  const outputDir = process.env.MALTEGO_MCP_OUTPUT_DIR ?? "/home/app/MaltegoGraphs";
  const outputPath = join(outputDir, outputFileName);

  const graph = new Graph(`phase1-${domain}`, `Phase 1: ${domain}`);
  const domainEntity = graph.addEntity({ type: "Domain", value: domain, properties: {} });

  const [dns, whois, crtsh] = await Promise.all([
    dnsLookup(domain),
    whoisLookup(domain),
    crtshLookup(domain),
  ]);

  if (dns.ok) {
    for (const ip of dns.data.a) {
      const ipEntity = graph.addEntity({ type: "IPv4Address", value: ip, properties: {} });
      graph.addLink({ from: domainEntity.id, to: ipEntity.id, label: "resolves_to", properties: { source: "dns" } });
      const asn = await asnLookup(ip);
      if (asn.ok) {
        const asnEntity = graph.addEntity({
          type: "AS",
          value: `AS${asn.data.asn}`,
          properties: { organization: asn.data.organization ?? "", country: asn.data.country ?? "" },
        });
        graph.addLink({ from: ipEntity.id, to: asnEntity.id, label: "hosted_in", properties: { source: "team-cymru" } });
      }
    }
    for (const ns of dns.data.ns) {
      const nsEntity = graph.addEntity({ type: "DNSName", value: ns, properties: {} });
      graph.addLink({ from: domainEntity.id, to: nsEntity.id, label: "has_nameserver", properties: { source: "dns" } });
    }
  } else {
    console.error(`dns lookup failed: ${dns.error}`);
  }

  if (whois.ok) {
    domainEntity.properties.registrar = whois.data.registrar ?? "";
    domainEntity.properties.creationDate = whois.data.creationDate ?? "";
  } else {
    console.error(`whois lookup failed: ${whois.error}`);
  }

  if (crtsh.ok) {
    for (const cert of crtsh.data.certs.slice(0, 20)) {
      const certEntity = graph.addEntity({
        type: "Certificate",
        value: cert.commonName,
        properties: { issuer: cert.issuer, notBefore: cert.notBefore, notAfter: cert.notAfter },
      });
      graph.addLink({ from: domainEntity.id, to: certEntity.id, label: "certificate", properties: { source: "crt.sh" } });
      for (const san of cert.sans) {
        if (san === domain) continue;
        const sanEntity = graph.ensureEntity({ type: "Domain", value: san, properties: {} });
        graph.addLink({ from: certEntity.id, to: sanEntity.id, label: "SAN", properties: { source: "crt.sh" } });
      }
    }
  } else {
    console.error(`crt.sh lookup failed: ${crtsh.error}`);
  }

  await writeMtgxFile(graph, outputPath);
  console.log(`wrote ${outputPath} (${graph.entityCount()} entities, ${graph.linkCount()} links)`);
  ```

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / ansible-playbook run against pve-tiny -- validation only in this step"
    - "Do not add a HEALTHCHECK, EXPOSE, or long-running CMD override -- Phase 1 has no HTTP port"

gates:
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml"
    expect: "exit 0"
    critical: true
  - id: driver-script-present
    cmd: "grep -c 'phase1-expand-domain.mjs' terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml"
    expect: "output >= 2"
    critical: true
```

---

### maltego-03-compose-service

```yaml
id: maltego-03-compose-service
title: Add the maltego-mcp service block to the mcp-utility-stack compose content
depends_on: [maltego-02-dockerfile-and-driver]

change: >
  In the existing "Write mcp-utility-stack docker-compose.yml" task's
  `content:` block (same file), add a new `maltego-mcp:` service entry
  under `services:`, as a sibling of `cve-mcp-server:` and `pgvector:`.
  Insert it directly after the `cve-mcp-server:` block, before `pgvector:`.
  Use exactly this YAML (indented to match the existing two-space service
  nesting):

  ```yaml
    maltego-mcp:
      build:
        context: ./maltego-mcp
      container_name: maltego-mcp
      # Phase 1 only -- no HTTP port, no long-running server. This service
      # is invoked on demand via `docker compose run --rm maltego-mcp node
      # phase1-expand-domain.mjs <domain> <outputFileName>`, never started
      # by `docker compose up`. See docs/maltego-integration/plan.md.
      profiles: ["tools"]
      volumes:
        - maltego-mcp-output:/home/app/MaltegoGraphs
  ```

  Then add `maltego-mcp-output:` as a new top-level named volume, as a
  sibling of the existing `mcp-home:` volume entry in the same compose
  content block's `volumes:` section.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / ansible-playbook run against pve-tiny -- validation only in this step"
    - "Do not add ports:, environment: MCP_ALLOWED_HOSTS, or restart: unless-stopped to this service -- it is not a daemon in Phase 1"

gates:
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml"
    expect: "exit 0"
    critical: true
  - id: compose-service-present
    cmd: "grep -c 'maltego-mcp-output' terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml"
    expect: "output >= 2"
    critical: true
```

---

### maltego-04-stack-contract

```yaml
id: maltego-04-stack-contract
title: Document maltego-mcp in mcp-utility-stack's STACK_CONTRACT.md
depends_on: [maltego-03-compose-service]

change: >
  In terraform/lxc/stacks/mcp-utility-stack/STACK_CONTRACT.md, find the
  "Provides" section's table (the one listing cve-mcp-server and
  docs-rag-mcp's service/port/protocol rows) and add a new row: service
  `maltego-mcp`, port `(none -- stdio/on-demand only, Phase 1)`, protocol
  `invoked via docker compose run --rm, not a daemon`, notes `domain ->
  DNS/WHOIS/ASN/crt.sh -> .mtgx, see docs/maltego-integration/plan.md`.
  Then find the "What Must Not Be Edited Casually" section and append one
  new bullet: "maltego-mcp has no `profiles` activation by default
  (`docker compose up -d` will not start it) -- this is deliberate, not a
  bug, because it speaks stdio and has nothing to serve as a background
  daemon in Phase 1. Do not add `restart: unless-stopped` or remove the
  `profiles: [\"tools\"]` line without re-reading
  docs/maltego-integration/README.md first."

scope:
  allowed_paths:
    - terraform/lxc/stacks/mcp-utility-stack/STACK_CONTRACT.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any edit to the Network, Dependencies, or VMID table rows -- this step only adds to Provides and the gotchas list"

gates:
  - id: maltego-row-present
    cmd: "grep -c 'maltego-mcp' terraform/lxc/stacks/mcp-utility-stack/STACK_CONTRACT.md"
    expect: "output >= 2"
    critical: true
```

---

## After the step-blocks (operator actions, not local-model steps)

These need a human, in this order -- not written as step-blocks because
each is either a one-time workstation action outside this repo, a
production mutation needing the normal approval flow, or a manual
Maltego Desktop check nothing here can script:

1. `git clone https://github.com/lidless-labs/maltego-mcp.git ~/git/maltego-mcp
   && cd ~/git/maltego-mcp && git checkout cb8100423d6cc4215e546f2c4125f5225d9dc282`
   -- pin to the exact commit that was inspected during planning (see
   `README.md`). Re-inspect before moving off this pin.
2. Deploy: `./with-secrets-prod-tiny scripts/provision.sh --stack mcp-utility-stack`
   under the normal production approval flow (Preflight Summary ->
   approval -> `TASK_APPROVAL` -> execute).
3. Run the Phase 1 test from the mcp-utility-stack LXC:
   `docker compose run --rm maltego-mcp node phase1-expand-domain.mjs
   example.com test-example-com.mtgx`, then confirm the file exists at
   `/opt/mcp-utility-stack/maltego-mcp-output/test-example-com.mtgx` (or
   via `docker run --rm -v maltego-mcp-output:/v busybox ls /v`) and that
   `unzip -l` on it shows `Graphs/Graph1.graphml`.
4. Copy the `.mtgx` file to a workstation with free Maltego Desktop
   installed and open it there. This is the actual milestone: does it
   open without error and show a legible graph. Record the result (and a
   screenshot if useful) in this workspace's `README.md`.
