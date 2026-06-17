"""NetBox custom script: DFD Annotation Questionnaire

Collect manual annotations for the threat-model config context and write
them back in-place. Deployed to /opt/netbox/netbox/scripts/ inside the
netbox container; appears under Operations → Scripts in the NetBox UI.
"""

from extras.scripts import BooleanVar, ChoiceVar, Script, StringVar, TextVar

_HARBOR_FLOW_IDS = (
    "df-p-apt-cacher-to-p-harbor",
    "df-p-authentik-to-p-harbor",
    "df-p-ci-runner-01-to-p-harbor",
    "df-p-dns-to-p-harbor",
    "df-p-monitoring-to-p-harbor",
    "df-p-netbox-to-p-harbor",
    "df-p-proxy-to-p-harbor",
    "df-p-step-ca-to-p-harbor",
)

_DS_FIELDS = (
    ("ds-authentik-db", "ds_authentik_db_encrypted"),
    ("ds-harbor-db", "ds_harbor_db_encrypted"),
    ("ds-harbor-storage", "ds_harbor_storage_encrypted"),
    ("ds-netbox-db", "ds_netbox_db_encrypted"),
    ("ds-monitoring-metrics", "ds_monitoring_metrics_encrypted"),
    ("ds-monitoring-logs", "ds_monitoring_logs_encrypted"),
    ("ds-step-ca-keys", "ds_step_ca_keys_encrypted"),
)


def _deep_copy_model(data):
    return {k: [dict(obj) for obj in v] if isinstance(v, list) else v for k, v in data.items()}


def _update_obj(model, section, obj_id, updates, warn):
    for obj in model.get(section, []):
        if obj.get("id") == obj_id:
            obj.update({k: v for k, v in updates.items() if v is not None})
            obj.pop("needs_annotation", None)
            obj.pop("annotation_hint", None)
            return
    warn(f"{section}: id '{obj_id}' not found — skipped")


def _apply_flow_annotations(model, data, warn):
    scope = data["user_to_traefik_scope"]
    _update_obj(model, "data_flows", "df-user-to-traefik", {
        "notes": "LAN-only — not internet-facing" if scope == "lan_only" else "Internet-facing — port-forwarded from WAN",
    }, warn)

    uses_https = data["apt_cacher_uses_https"]
    _update_obj(model, "data_flows", "df-apt-cacher-upstream", {
        "transport_security": "tls" if uses_https else "plaintext",
        "notes": "Uses HTTPS upstream mirrors" if uses_https else "Uses HTTP upstream mirrors (unencrypted transit)",
    }, warn)

    harbor_auth = "robot-account" if data["harbor_pull_auth"] == "robot_account" else "anonymous"
    harbor_notes = data.get("harbor_pull_auth_notes") or None
    for fid in _HARBOR_FLOW_IDS:
        _update_obj(model, "data_flows", fid, {"auth": harbor_auth, "notes": harbor_notes}, warn)

    loki_updates = {"auth": data["loki_push_auth"], "log_filtering": data["loki_log_filtering"]}
    for fid in ("df-authentik-to-loki", "df-netbox-to-loki"):
        _update_obj(model, "data_flows", fid, loki_updates, warn)

    if data["monitoring_scrapes_confirmed"]:
        for fid in ("df-monitoring-scrape-authentik", "df-monitoring-scrape-netbox"):
            _update_obj(model, "data_flows", fid, {"confirmed": True}, warn)


def _apply_store_annotations(model, data, warn):
    for ds_id, field in _DS_FIELDS:
        _update_obj(model, "data_stores", ds_id, {"encryption_at_rest": data[field]}, warn)


def _apply_process_annotations(model, data, warn):
    ci_updates = {"scope": data["ci_runner_scope"]}
    if data.get("ci_runner_notes"):
        ci_updates["notes"] = data["ci_runner_notes"]
    _update_obj(model, "processes", "p-ci-runner-01", ci_updates, warn)


def _count_needs_annotation(model):
    return sum(
        1
        for section in ("data_flows", "processes", "data_stores")
        for obj in model.get(section, [])
        if obj.get("needs_annotation")
    )


class DFDAnnotationQuestionnaire(Script):
    class Meta:
        name = "DFD Annotation Questionnaire"
        description = (
            "Fill in manual annotations to flesh out the threat model DFD. "
            "Updates the 'threat-model' config context in-place."
        )
        scheduling_enabled = False
        commit_default = True

    # -------------------------------------------------------------------------
    # Internet exposure
    # -------------------------------------------------------------------------

    user_to_traefik_scope = ChoiceVar(
        label="Is tcp/443 internet-facing?",
        description="Trust boundary for df-user-to-traefik (external user → Traefik).",
        choices=[
            ("lan_only", "LAN-only — not internet-facing"),
            ("internet", "Internet-facing (port-forwarded from WAN)"),
        ],
        default="lan_only",
    )

    # -------------------------------------------------------------------------
    # apt-cacher upstream
    # -------------------------------------------------------------------------

    apt_cacher_uses_https = BooleanVar(
        label="apt-cacher uses HTTPS upstream mirrors",
        description="Does apt-cacher-ng use https:// upstream mirrors? (df-apt-cacher-upstream)",
        default=False,
    )

    # -------------------------------------------------------------------------
    # Harbor pull auth — applies to all LXC → Harbor flows
    # -------------------------------------------------------------------------

    harbor_pull_auth = ChoiceVar(
        label="LXC → Harbor pull auth",
        description=(
            "Do LXC containers authenticate to Harbor for image pulls? "
            "Applied to: apt-cacher, authentik, ci-runner-01, dns, monitoring, "
            "netbox, proxy, step-ca → harbor."
        ),
        choices=[
            ("anonymous", "Anonymous — no credentials required"),
            ("robot_account", "Robot account — per-stack or shared"),
        ],
        default="robot_account",
    )
    harbor_pull_auth_notes = StringVar(
        label="Harbor pull auth details",
        description="e.g. 'single shared harbor-readonly account' or 'per-stack robot accounts'",
        required=False,
    )

    # -------------------------------------------------------------------------
    # Loki push
    # -------------------------------------------------------------------------

    loki_push_auth = ChoiceVar(
        label="Loki push auth",
        description="Auth for log pushes to Loki. (df-authentik-to-loki, df-netbox-to-loki)",
        choices=[
            ("none", "None — unauthenticated push"),
            ("bearer_token", "Bearer token"),
        ],
        default="none",
    )
    loki_log_filtering = BooleanVar(
        label="Logs filtered before Loki",
        description="Are logs redacted to remove secrets before being pushed to Loki?",
        default=False,
    )

    # -------------------------------------------------------------------------
    # Monitoring scrapes
    # -------------------------------------------------------------------------

    monitoring_scrapes_confirmed = BooleanVar(
        label="Confirm monitoring scrape targets",
        description=(
            "Confirm VictoriaMetrics scrape config targets authentik and netbox hosts. "
            "(df-monitoring-scrape-authentik, df-monitoring-scrape-netbox)"
        ),
        default=True,
    )

    # -------------------------------------------------------------------------
    # Data stores: encryption at rest
    # -------------------------------------------------------------------------

    ds_authentik_db_encrypted = BooleanVar(
        label="Authentik DB encrypted at rest",
        description="Is the postgres data volume for Authentik encrypted?",
        default=False,
    )
    ds_harbor_db_encrypted = BooleanVar(
        label="Harbor DB encrypted at rest",
        default=False,
    )
    ds_harbor_storage_encrypted = BooleanVar(
        label="Harbor storage encrypted at rest",
        description="Is the Harbor image blob storage volume encrypted?",
        default=False,
    )
    ds_netbox_db_encrypted = BooleanVar(
        label="NetBox DB encrypted at rest",
        default=False,
    )
    ds_monitoring_metrics_encrypted = BooleanVar(
        label="Monitoring metrics encrypted at rest",
        description="Is the VictoriaMetrics storage volume encrypted?",
        default=False,
    )
    ds_monitoring_logs_encrypted = BooleanVar(
        label="Monitoring logs encrypted at rest",
        description="Is the Loki log store encrypted?",
        default=False,
    )
    ds_step_ca_keys_encrypted = BooleanVar(
        label="step-ca keys encrypted at rest",
        description="Does step-ca use a passphrase to encrypt the CA private key on disk?",
        default=False,
    )

    # -------------------------------------------------------------------------
    # CI runner
    # -------------------------------------------------------------------------

    ci_runner_scope = ChoiceVar(
        label="CI runner registration scope",
        description="Repo-scoped = lower blast radius if runner is compromised.",
        choices=[
            ("repo", "Repository-scoped"),
            ("org", "Organisation-scoped"),
        ],
        default="repo",
    )
    ci_runner_notes = StringVar(
        label="CI runner notes",
        description="e.g. secrets available at runtime, workflow trigger restrictions.",
        required=False,
    )

    # -------------------------------------------------------------------------
    # Free text
    # -------------------------------------------------------------------------

    general_notes = TextVar(
        label="General notes",
        description="Any additional threat model context.",
        required=False,
    )

    # -------------------------------------------------------------------------

    def run(self, data, commit):
        from extras.models import ConfigContext

        ctx = ConfigContext.objects.get(name="threat-model")
        model = _deep_copy_model(ctx.data)

        _apply_flow_annotations(model, data, self.log_warning)
        _apply_store_annotations(model, data, self.log_warning)
        _apply_process_annotations(model, data, self.log_warning)

        if data.get("general_notes"):
            model["notes"] = data["general_notes"]

        remaining = _count_needs_annotation(model)

        if commit:
            ctx.data = model
            ctx.save()
            self.log_success(f"threat-model config context updated. Remaining needs_annotation: {remaining}")
        else:
            self.log_info(f"Dry run — no changes saved. Would leave {remaining} needs_annotation items.")
