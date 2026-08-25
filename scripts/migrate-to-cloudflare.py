# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# This script deliberately uses only the Python standard library so
# that `uv run scripts/migrate-to-cloudflare.py ...` works without
# installing any packages (the empty `dependencies` list above is what
# makes uv skip dependency resolution entirely). A plain
# `python3 scripts/migrate-to-cloudflare.py ...` works too.
"""Migrate a Quarto site from Netlify to Cloudflare Workers, from the terminal.

This script automates every step of the migration described in MIGRATE.md:

    check    verify tools, credentials, and current DNS state
    generate write wrangler.toml and .github/workflows/publish.yml
    secrets  push CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID to GitHub
    build    run the site's render command (mirrors CI)
    deploy   upload ./_site with wrangler deploy (reads wrangler.toml)
    domain   bind the custom domain(s) through the Cloudflare API,
             replacing the old Netlify DNS records automatically
    verify   run the dig/curl checks from RUNBOOK.md
    rollback restore the pre-migration DNS records from the snapshot
    cleanup  delete leftover Netlify DNS records (after all checks pass)
    all      check -> generate -> secrets -> build -> deploy -> domain
             -> verify   (rollback and cleanup are always explicit)

Only one step cannot be automated by anything: creating the Cloudflare
API token in the dashboard. Everything else is a terminal command.

Every action the script takes is labeled as it runs, so you can always
see what is happening:

    [shell]      an external program was executed (shown after '$')
    [cloudflare] a Cloudflare API request (method, path, body, result)
    [file]       a file was written or backed up on disk

Stages that change DNS (domain, rollback, cleanup) ask for
confirmation first; pass --yes to skip the prompt.

Usage (run from inside the target site's repository):

    uv run scripts/migrate-to-cloudflare.py \
        --config scripts/migrate-configs/developerdevelopment.toml \
        --stage all

Requires: Python 3.11+, curl, git, and (for deploy) npx wrangler.
Cloudflare credentials come from the CLOUDFLARE_API_TOKEN and
CLOUDFLARE_ACCOUNT_ID environment variables.
"""

import argparse
import json
import os
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

API = "https://api.cloudflare.com/client/v4"
STATE_FILE = Path(".cloudflare-migration-state.json")
NETLIFY_APEX_IP = "75.2.60.5"

INDENT = "  "


# ---------------------------------------------------------------- helpers


def die(message: str) -> None:
    """Print an error and exit with a non-zero status."""
    print(f"ERROR: {message}")
    sys.exit(1)


def info(message: str) -> None:
    """Print an informational line."""
    print(f"{INDENT}{message}")


def run(command: str, check: bool = True, capture: bool = False) -> str:
    """Run a shell command, echoing it first with a [shell] label."""
    print(f"[shell] $ {command}")
    result = subprocess.run(
        command,
        shell=True,
        check=False,
        text=True,
        capture_output=capture,
    )
    if check and result.returncode != 0:
        output = result.stderr if capture else ""
        die(f"command failed ({result.returncode}): {command}\n{output}")
    return result.stdout if capture else ""


def api(
    method: str,
    path: str,
    token: str,
    body: dict | None = None,
) -> dict:
    """Call the Cloudflare API via curl and return the JSON response.

    curl is used instead of urllib deliberately: it uses the system
    certificate store, which works on every platform (urllib inside
    `uv run` cannot see the CA certificates on NixOS, for example).
    Every request and its outcome is printed with a [cloudflare] label
    so it is always clear what the script is doing on your account.
    """
    url = f"{API}{path}"
    print(f"[cloudflare] {method} {path}")
    if body is not None:
        # show the request body, but never print credentials
        printable = {
            key: value
            for key, value in body.items()
            if "token" not in key.lower() and "authorization" not in key.lower()
        }
        print(f"[cloudflare]   body: {json.dumps(printable)}")
    command = [
        "curl",
        "-sS",
        "-X",
        method,
        url,
        "-H",
        "Authorization: Bearer " + token,
        "-H",
        "Content-Type: application/json",
        "-w",
        "\n%{http_code}",
    ]
    if body is not None:
        command += ["--data-binary", json.dumps(body)]
    result = subprocess.run(
        command, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        die(f"curl failed ({result.returncode}): {result.stderr.strip()}")
    output, _, status = result.stdout.rpartition("\n")
    status = status.strip()
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        payload = {"errors": [{"message": output[:500] or "empty response"}]}
    if not status.startswith("2"):
        messages = "; ".join(
            error_item.get("message", "?")
            for error_item in payload.get("errors", [])
        )
        print(f"[cloudflare]   -> HTTP {status} ERROR: {messages}")
        codes = [e.get("code") for e in payload.get("errors", [])]
        raise CloudflareApiError(messages, codes)
    print(f"[cloudflare]   -> HTTP {status} OK")
    return payload


class CloudflareApiError(Exception):
    """A non-2xx response from the Cloudflare API."""

    def __init__(self, message: str, codes: list) -> None:
        super().__init__(message)
        self.codes = codes


def load_config(path: str) -> dict:
    """Read the per-site TOML configuration file."""
    config_path = Path(path)
    if not config_path.is_file():
        die(f"config file not found: {path}")
    with config_path.open("rb") as handle:
        config = tomllib.load(handle)
    required = [
        "worker_name",
        "apex",
        "github_repo",
        "render_command",
    ]
    for key in required:
        if key not in config:
            die(f"config is missing the required key '{key}': {path}")
    return config


def load_state() -> dict:
    """Load the DNS snapshot taken before the cutover."""
    if not STATE_FILE.is_file():
        die(
            f"no snapshot file ({STATE_FILE}) in the current directory; "
            "run the 'domain' stage first (it snapshots DNS automatically)"
        )
    with STATE_FILE.open() as handle:
        return json.load(handle)


def save_state(state: dict) -> None:
    """Persist the DNS snapshot for use by 'rollback'."""
    with STATE_FILE.open("w") as handle:
        json.dump(state, handle, indent=2)
    print(f"{INDENT}saved DNS snapshot to {STATE_FILE}")


def get_token() -> str:
    """Return the Cloudflare API token from the environment."""
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token:
        die(
            "CLOUDFLARE_API_TOKEN is not set; export it first "
            "(create the token once in the Cloudflare dashboard)"
        )
    return token


def get_account_id() -> str:
    """Return the Cloudflare account ID from the environment."""
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not account_id:
        die(
            "CLOUDFLARE_ACCOUNT_ID is not set; export it first "
            "(it is the 32-character hex id visible in dashboard URLs)"
        )
    return account_id


def zone_id_for(token: str, apex: str) -> str:
    """Look up the zone id for an apex domain."""
    response = api("GET", f"/zones?name={apex}", token)
    results = response.get("result", [])
    if not results:
        die(f"zone not found for {apex} (is it on this Cloudflare account?)")
    return results[0]["id"]


def dns_records(token: str, zone: str, name: str) -> list:
    """Return the DNS records for one hostname in a zone."""
    response = api("GET", f"/zones/{zone}/dns_records?name={name}", token)
    return response.get("result", [])


def is_netlify_record(record: dict) -> bool:
    """Is this DNS record part of the old Netlify setup?"""
    if record.get("type") == "A" and record.get("content") == NETLIFY_APEX_IP:
        return True
    return (
        record.get("type") in ("CNAME", "A")
        and record.get("content", "").endswith("netlify.app")
    )


def http_status(url: str) -> tuple:
    """Return (status, location) for a URL using curl."""
    output = run(
        f"curl -s -o /dev/null -w '%{{http_code}} %{{redirect_url}}' {url}",
        check=False,
        capture=True,
    ).strip()
    parts = output.split(" ", 1)
    status = parts[0]
    location = parts[1] if len(parts) > 1 else ""
    return status, location


# ----------------------------------------------------------------- stages


def stage_check(config: dict) -> None:
    """Verify tools, credentials, and the current DNS state."""
    print("[check] verifying prerequisites")
    for tool in ("quarto", "curl", "git", "npx", "gh"):
        probe = run(f"command -v {tool}", check=False, capture=True).strip()
        if probe:
            info(f"{tool}: {probe}")
        else:
            info(f"{tool}: MISSING (install it before continuing)")
    if os.environ.get("CLOUDFLARE_API_TOKEN"):
        info("CLOUDFLARE_API_TOKEN: set")
    else:
        info("CLOUDFLARE_API_TOKEN: NOT set (needed for secrets/domain/verify)")
    if os.environ.get("CLOUDFLARE_ACCOUNT_ID"):
        info("CLOUDFLARE_ACCOUNT_ID: set")
    else:
        info("CLOUDFLARE_ACCOUNT_ID: NOT set")
    run("gh auth status", check=False)
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if token:
        apex = config["apex"]
        zone = zone_id_for(token, apex)
        info(f"zone {apex}: {zone}")
        for name in (apex, f"www.{apex}"):
            records = dns_records(token, zone, name)
            for record in records:
                flag = " <-- Netlify" if is_netlify_record(record) else ""
                info(
                    f"DNS {record['type']} {name} -> "
                    f"{record['content']}{flag}"
                )
    info(
        "run 'wrangler login' once (or rely on CLOUDFLARE_API_TOKEN) "
        "before the deploy stage"
    )


def wrangler_toml(config: dict) -> str:
    """Render the contents of wrangler.toml for this site."""
    lines = [
        "# Wrangler configuration for " + config["apex"],
        "# Generated by scripts/migrate-to-cloudflare.py; see MIGRATE.md.",
        "",
        f'name = "{config["worker_name"]}"',
        f'compatibility_date = "{datetime.now().strftime("%Y-%m-%d")}"',
        "",
        "[assets]",
        'directory = "./_site"',
    ]
    if config.get("not_found_handling"):
        lines.append(
            f'not_found_handling = "{config["not_found_handling"]}"'
        )
    lines.extend(
        [
            "",
            "# Custom-domain binding is intentionally left commented out:",
            "# the 'domain' stage of scripts/migrate-to-cloudflare.py binds",
            "# the domains through the Cloudflare API instead (it can also",
            "# replace the old Netlify DNS records, which wrangler cannot).",
            "# Uncomment to let wrangler deploy manage the bindings instead.",
        ]
    )
    for name in (config["apex"], "www." + config["apex"]):
        lines.extend(
            [
                "",
                "# [[routes]]",
                f'# pattern = "{name}"',
                "# custom_domain = true",
            ]
        )
    return "\n".join(lines) + "\n"


def publish_workflow(config: dict) -> str:
    """Render the GitHub Actions workflow that renders and deploys."""
    # each workflow_setup element is a raw, pre-indented YAML line
    setup = "\n".join(config.get("workflow_setup", []))
    render = config["render_command"]
    env_block = ""
    for key, value in config.get("render_env", {}).items():
        env_block += f"\n        env:\n          {key}: {value}"
    setup_block = ""
    if setup:
        setup_block = f"\n{setup}"
    token_ref = "${{ secrets.CLOUDFLARE_API_TOKEN }}"
    account_ref = "${{ secrets.CLOUDFLARE_ACCOUNT_ID }}"
    gh_token_ref = "${{ secrets.GITHUB_TOKEN }}"
    return (
        "# Generated by scripts/migrate-to-cloudflare.py; see MIGRATE.md.\n"
        "name: Publish\n"
        "\n"
        "on:\n"
        "  push:\n"
        f"    branches: [ {config.get('branch', 'main')} ]\n"
        "\n"
        "jobs:\n"
        "  build-deploy:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Check out Repository\n"
        "        uses: actions/checkout@v3\n"
        "        with:\n"
        "          submodules: true\n"
        "\n"
        "      - name: Set up Quarto\n"
        "        uses: quarto-dev/quarto-actions/setup@v2\n"
        "        with:\n"
        f"          version: {config.get('quarto_version', '1.5.56')}\n"
        f"{setup_block}"
        "\n"
        "      - name: Render the Site\n"
        f"{env_block}\n"
        f"        run: {render}\n"
        "\n"
        "      - name: Deploy to Cloudflare Workers\n"
        "        if: github.event_name == 'push'\n"
        "        uses: cloudflare/wrangler-action@v3\n"
        "        with:\n"
        f"          apiToken: {token_ref}\n"
        f"          accountId: {account_ref}\n"
        "          command: deploy\n"
        f"          gitHubToken: {gh_token_ref}\n"
    )


def confirm(question: str, assume_yes: bool) -> None:
    """Ask before any stage that changes DNS or the Cloudflare account."""
    if assume_yes:
        info("--yes given: skipping the confirmation prompt")
        return
    answer = input(f"\n  {question}\n  Type 'yes' to continue: ")
    if answer.strip().lower() != "yes":
        die("aborted (nothing was changed)")


def stage_generate(config: dict) -> None:
    """Write wrangler.toml and .github/workflows/publish.yml."""
    print("[generate] writing configuration files")
    toml_path = Path("wrangler.toml")
    if toml_path.exists():
        info("wrangler.toml already exists; leaving it in place")
    else:
        toml_path.write_text(wrangler_toml(config))
        print(f"[file] wrote {toml_path}")
    workflow_dir = Path(".github/workflows")
    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_path = workflow_dir / "publish.yml"
    if workflow_path.exists():
        backup = workflow_path.with_suffix(".yml.netlify-backup")
        backup.write_text(workflow_path.read_text())
        print(f"[file] backed up existing workflow to {backup.name}")
    workflow_path.write_text(publish_workflow(config))
    print(f"[file] wrote {workflow_path}")
    info(
        "review both files, then commit and push them so that CI deploys "
        "on every future push (this script never commits)"
    )


def stage_secrets(config: dict) -> None:
    """Push the Cloudflare credentials to the GitHub repository."""
    print("[secrets] setting GitHub Actions secrets")
    get_account_id()  # fail early if unset
    get_token()  # fail early if unset
    repo = config["github_repo"]
    # the values are passed through shell variables so that the
    # secrets never appear in the echoed command or in process lists
    run(
        'gh secret set CLOUDFLARE_API_TOKEN '
        '--repo ' + repo + ' --body "$CLOUDFLARE_API_TOKEN"'
    )
    run(
        'gh secret set CLOUDFLARE_ACCOUNT_ID '
        '--repo ' + repo + ' --body "$CLOUDFLARE_ACCOUNT_ID"'
    )
    info(f"secrets are set on {repo}")


def stage_build(config: dict) -> None:
    """Render the site exactly as CI will."""
    print("[build] rendering the site")
    run(config["render_command"])
    if not Path("_site/index.html").is_file():
        die("render finished but _site/index.html does not exist")
    info("_site/index.html exists")


def stage_deploy(config: dict) -> None:
    """Deploy ./_site as the Worker's static assets."""
    print("[deploy] uploading the site to Cloudflare Workers")
    deploy_command = config.get(
        "deploy_command", "npx wrangler deploy"
    )
    run(deploy_command)
    token = get_token()
    account_id = get_account_id()
    response = api(
        "GET", f"/accounts/{account_id}/workers/scripts", token
    )
    names = [item.get("name") for item in response.get("result", [])]
    if config["worker_name"] not in names:
        die(
            f"worker {config['worker_name']} not found after deploy "
            f"(scripts: {names})"
        )
    info(f"worker {config['worker_name']} exists")
    subdomain = api(
        "GET", f"/accounts/{account_id}/workers/subdomain", token
    ).get("result", {}).get("subdomain", "<subdomain>")
    info(
        f"sanity-check URL: https://{config['worker_name']}."
        f"{subdomain}.workers.dev"
    )


def attach_domain(
    token: str, account_id: str, zone: str, hostname: str, worker: str
) -> None:
    """Attach one hostname as a custom domain, replacing old DNS."""
    body = {
        "environment": "production",
        "hostname": hostname,
        "service": worker,
        "zone_id": zone,
        "override_existing_dns_record": True,
        "override_existing_origin": True,
        "override_existing_active_worker": True,
    }
    try:
        api("PUT", f"/accounts/{account_id}/workers/domains", token, body)
        info(f"bound {hostname} to {worker}")
        return
    except CloudflareApiError as error:
        info(
            f"direct attach of {hostname} failed ({error}); "
            "deleting conflicting Netlify records and retrying"
        )
    records = dns_records(token, zone, hostname)
    for record in records:
        if is_netlify_record(record):
            api(
                "DELETE",
                f"/zones/{zone}/dns_records/{record['id']}",
                token,
            )
            info(
                f"deleted Netlify record "
                f"{record['type']} {hostname} -> {record['content']}"
            )
    api("PUT", f"/accounts/{account_id}/workers/domains", token, body)
    info(f"bound {hostname} to {worker}")


def stage_domain(config: dict, assume_yes: bool = False) -> None:
    """Snapshot DNS, then bind apex and www to the Worker."""
    print("[domain] binding custom domains (apex first)")
    confirm(
        f"This will replace the DNS records for {config['apex']} and "
        f"www.{config['apex']} so they point at the Cloudflare Worker "
        f"{config['worker_name']} instead of Netlify. A DNS snapshot is "
        "saved first so 'rollback' can restore them.",
        assume_yes,
    )
    token = get_token()
    account_id = get_account_id()
    apex = config["apex"]
    zone = zone_id_for(token, apex)
    hostnames = [apex, f"www.{apex}"]
    snapshot = {
        "taken_at": datetime.now().isoformat(),
        "zone_id": zone,
        "apex": apex,
        "records": {},
    }
    for name in hostnames:
        snapshot["records"][name] = dns_records(token, zone, name)
    save_state(snapshot)
    info("snapshot saved; rollback is available with --stage rollback")
    for name in hostnames:
        attach_domain(token, account_id, zone, name, config["worker_name"])
    info("waiting 30 seconds for DNS to propagate before checks...")
    run("sleep 30", check=False)


def stage_verify(config: dict) -> None:
    """Run the RUNBOOK.md dig/curl checks."""
    print("[verify] checking the live site")
    apex = config["apex"]
    failures = 0
    for url in (f"https://{apex}/", f"https://www.{apex}/"):
        status, location = http_status(url)
        if status == "200":
            info(f"OK  {url} -> 200")
        else:
            failures += 1
            info(f"FAIL {url} -> {status} {location}")
    for url in (f"https://{apex}/this-does-not-exist",):
        status, _ = http_status(url)
        # either a custom 404 page (200 after redirect) or a plain 404
        if status in ("200", "301", "302", "307", "308", "404"):
            info(f"OK  {url} -> {status} (expected)")
        else:
            failures += 1
            info(f"FAIL {url} -> {status}")
    for name in (apex, f"www.{apex}"):
        output = run(f"dig +short {name}", check=False, capture=True)
        if "netlify" in output:
            failures += 1
            info(f"FAIL {name} still resolves to Netlify: {output.strip()}")
        else:
            info(f"OK  {name} no longer resolves to Netlify")
    if failures:
        die(f"{failures} verification check(s) failed; see above")
    info("all verification checks passed")


def stage_rollback(config: dict, assume_yes: bool = False) -> None:
    """Restore the Netlify DNS records from the snapshot."""
    print("[rollback] restoring pre-migration DNS records")
    confirm(
        "This will delete the current DNS records for the site and "
        "restore the Netlify records saved in the snapshot.",
        assume_yes,
    )
    token = get_token()
    state = load_state()
    zone = state["zone_id"]
    for name, records in state["records"].items():
        existing = dns_records(token, zone, name)
        for record in existing:
            api(
                "DELETE",
                f"/zones/{zone}/dns_records/{record['id']}",
                token,
            )
            info(f"removed current record {record['type']} {name}")
        for record in records:
            body = {
                "type": record["type"],
                "name": record["name"],
                "content": record["content"],
                "ttl": record.get("ttl", 1),
                "proxied": record.get("proxied", True),
            }
            api("POST", f"/zones/{zone}/dns_records", token, body)
            info(
                f"restored {record['type']} {record['name']} "
                f"-> {record['content']}"
            )
    info(
        "DNS points back at Netlify; the Worker keeps running on its "
        "*.workers.dev URL until you delete it"
    )


def stage_cleanup(config: dict, assume_yes: bool = False) -> None:
    """Delete any leftover Netlify DNS records (post-verification)."""
    print("[cleanup] removing leftover Netlify DNS records")
    confirm(
        "This will delete any remaining Netlify DNS records. Run this "
        "only after 'verify' has passed.",
        assume_yes,
    )
    token = get_token()
    apex = config["apex"]
    zone = zone_id_for(token, apex)
    removed = 0
    for name in (apex, f"www.{apex}"):
        for record in dns_records(token, zone, name):
            if is_netlify_record(record):
                api(
                    "DELETE",
                    f"/zones/{zone}/dns_records/{record['id']}",
                    token,
                )
                removed += 1
                info(
                    f"deleted {record['type']} {name} "
                    f"-> {record['content']}"
                )
    if removed == 0:
        info("no Netlify records remain (they were replaced at binding)")
    info(
        "finally, delete the Netlify app in the Netlify dashboard "
        "(or: netlifyctl, or the Netlify API) -- this is the last step"
    )


STAGES = {
    "check": stage_check,
    "generate": stage_generate,
    "secrets": stage_secrets,
    "build": stage_build,
    "deploy": stage_deploy,
    "domain": stage_domain,
    "verify": stage_verify,
    "rollback": stage_rollback,
    "cleanup": stage_cleanup,
}


def main() -> None:
    """Parse arguments and run the requested stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", required=True, help="path to the per-site TOML config"
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=list(STAGES) + ["all"],
        help="migration stage to run",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the confirmation prompt on DNS-changing stages",
    )
    arguments = parser.parse_args()
    config = load_config(arguments.config)
    order = [
        "check",
        "generate",
        "secrets",
        "build",
        "deploy",
        "domain",
        "verify",
    ]
    stages = order if arguments.stage == "all" else [arguments.stage]
    print(
        f"site: {config['apex']}  worker: {config['worker_name']}  "
        f"stage(s): {', '.join(stages)}"
    )
    for name in stages:
        print(f"\n=== stage: {name} ===")
        try:
            if name in ("domain", "rollback", "cleanup"):
                STAGES[name](config, assume_yes=arguments.yes)
            else:
                STAGES[name](config)
        except CloudflareApiError as error:
            die(
                "the Cloudflare API rejected the request above. If it is "
                "an authentication error, check that "
                "CLOUDFLARE_API_TOKEN/CLOUDFLARE_ACCOUNT_ID are correct; "
                f"the API said: {error}"
            )
    print(
        "\ndone. Every action above was labeled as it ran:\n"
        "  [shell]      an external program ran (the line after '$')\n"
        "  [cloudflare] a Cloudflare API request was made (method, path,\n"
        "               request body, and HTTP result)\n"
        "  [file]       a file was written or backed up on disk\n"
        "  indented     informational output or the result of a check"
    )


if __name__ == "__main__":
    main()
