# maltego-integration — plan

**Status 2026-10-02: Phases 1-3 (+3b) all done and confirmed live.**
This file's step-blocks below are Phase 1's literal, already-executed
plan (kept as the historical record of what was actually run — don't
re-run them). Phases 2/3 happened as direct follow-on implementation
work once Phase 1 was confirmed, not as further step-blocks in this
file — the full narrative, every real bug found, and every live
verification is in `README.md`, which is the up-to-date source of truth
for status. Summary:

- **Phase 2 Tier 1 (VirusTotal/Shodan/GreyNoise)** — done. New tools
  added directly to `maltego-mcp`'s driver (`investigate.ts`), not to
  `cve-mcp-server` — decided after reconsidering mid-stream: `cve-mcp-
  server`'s name, repo, and contract are CVE-only, and its one real
  consumer (`cve_enrichment_sync.py`) has nothing to do with Maltego
  investigations. Mixing them would share one quota/blast-radius story
  across two unrelated purposes with no record of why.
- **Phase 2 Tier 2 (AlienVault OTX)** — done, real key live in OpenBao.
- **Phase 2 Tier 3 (OCCRP Aleph)** — dropped. Needs a vetted journalist/
  public-interest application, not a self-serve signup; a poor fit for
  a homelab lab with no guarantee of approval.
- **Phase 3 (`osint-mcp`)** — done. A new, purpose-built Streamable HTTP
  MCP server (same precedent as `docs-rag-mcp`: in-repo, not vendored)
  exposing `investigate_domain`, with real bearer-token auth (the brief
  asked for this even on LAN; `cve-mcp-server`/`docs-rag-mcp` have none
  — this is the first service to actually do it).
- **Phase 3b (`deep-research-agent` wiring)** — done. The Searcher
  sub-agent now holds `osint_investigate`, a real
  `agent_framework.MCPStreamableHTTPTool` — the first `MCPTool` this
  codebase has used. Confirmed live in the running production container.
- **Phase 4** (interactive Maltego Desktop transform) and **Phase 5**
  (investigation persistence) — not started.

Target: `mcp-utility-stack` (`ai_seg`, pve-tiny, LXC VMID 50011,
`192.168.50.10`) — the existing MCP services' home. Deployment file:
`terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml`.

## Before running any step below (already done — historical record)

`maltego-01-vendor-source` copies from a local clone on the ansible
controller (this operator's workstation), same pattern as `cve-mcp-server`'s
own `mcp_source_dir`. This was the one-time setup needed before the first
run of `maltego-01` (already done 2026-10-02):

```bash
git clone https://github.com/lidless-labs/maltego-mcp.git ~/git/maltego-mcp
cd ~/git/maltego-mcp
git checkout cb8100423d6cc4215e546f2c4125f5225d9dc282
```

This pins to the exact commit inspected during planning (see `README.md`).
Re-inspect the source before ever moving this pin forward.

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

````yaml
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

  ```dockerfile
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
````

---

### maltego-03-compose-service

````yaml
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
````

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

## After the step-blocks (done — historical record)

These needed a human, and all three happened 2026-10-02 (with several
real bugs found and fixed in between — see `README.md`'s full account,
not just this summary):

1. Deploy: `./with-secrets-prod-tiny scripts/provision.sh --stack mcp-utility-stack`
   — done, after fixing 7 real bugs surfaced by actually deploying.
2. Ran the Phase 1 test from the mcp-utility-stack LXC — produced a
   valid `.mtgx` confirmed via `unzip -l`.
3. Operator opened the file in real Maltego Desktop 4.13.0 — **initially
   hung indefinitely with no error** (a real bug in `maltego-mcp`'s own
   writer, not file corruption — see `README.md`'s "The real finding"
   section for the full root-cause story). Fixed with a native writer;
   confirmed rendering correctly (icons, values, links, topology) on
   retest. This was the actual Phase 1 milestone, and it's done.

Phases 2-3b then followed as direct implementation (not further
step-blocks) once this milestone was confirmed — see `README.md`.
