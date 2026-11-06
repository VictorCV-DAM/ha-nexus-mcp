import os
import subprocess
import json
import urllib.request
import time

os.chdir(r"D:\HITOS - Víctor Antigravity\ha-nexus-mcp")

print("1. Git commit, tag and push v1.5.4...")
subprocess.run(["git", "add", "-A"], check=True)
subprocess.run(["git", "commit", "-m", "chore(release): bump version to v1.5.4 with target exposure enforcement"], check=True)
subprocess.run(["git", "tag", "-a", "v1.5.4", "-m", "Release v1.5.4"], check=True)
subprocess.run(["git", "push", "origin", "main"], check=True)
subprocess.run(["git", "push", "origin", "v1.5.4"], check=True)
print("Git push successful!")

print("2. Getting GitHub token...")
p = subprocess.Popen(["git", "credential", "fill"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
stdout, _ = p.communicate("protocol=https\nhost=github.com\n\n")
token = None
for line in stdout.splitlines():
    if line.startswith("password="):
        token = line.split("password=", 1)[1]
        break

assert token, "Token not found!"

print("3. Publishing GitHub Release v1.5.4 (letting GitHub Actions attach nexus_mcp.zip)...")
release_title = "v1.5.4 - Mandatory Target Exposure Enforcement & Clean Release Packaging"
release_notes = """## Nexus MCP v1.5.4

### 🚀 Highlights & Fixes in v1.5.4:
- **Mandatory Target Exposure Enforcement in `ha_call_service`:**
  - `ha_call_service` in `tools.py` now strictly mandates that every service execution must target at least one exposed entity via `entity_id` (`async_should_expose`).
  - Target-less service calls (such as `backup.create`, `recorder.purge`, `notify.*`, or unexposed `script.<name>`) are categorically rejected.
  - Calling scripts via `script.<name>` normalizes the script as target `script.<name>` and validates Assist exposure, preventing voice satellites or Assist sessions without user context from reaching unexposed or administrative scripts.
- **Pure GitHub Actions Release Packaging:**
  - Release asset `nexus_mcp.zip` is built and attached exclusively by the official `.github/workflows/release.yml` GitHub Actions CI pipeline, guaranteeing zero byte-compiled artifacts (`.pyc` / `__pycache__`).
- **Cache Busting:**
  - Lovelace resources and frontend card bumped to `?v=1.5.4`.
"""

rel_payload = {
    "tag_name": "v1.5.4",
    "name": release_title,
    "body": release_notes,
    "draft": False,
    "prerelease": False
}

req = urllib.request.Request(
    "https://api.github.com/repos/VictorCV-DAM/ha-nexus-mcp/releases",
    data=json.dumps(rel_payload).encode(),
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    method="POST"
)

with urllib.request.urlopen(req) as resp:
    rel_data = json.loads(resp.read().decode())
    rel_id = rel_data["id"]
    rel_html = rel_data.get("html_url")
    print(f"Created Release {rel_id}: {rel_html}")

print("4. Waiting for GitHub Actions workflow (release.yml) to build and attach nexus_mcp.zip...")
workflow_completed = False
asset_url = None

for i in range(24): # wait up to 120s
    time.sleep(5)
    chk_req = urllib.request.Request(
        f"https://api.github.com/repos/VictorCV-DAM/ha-nexus-mcp/releases/{rel_id}",
        headers={"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(chk_req) as resp:
        rel_info = json.loads(resp.read().decode())
        assets = rel_info.get("assets", [])
        zip_assets = [a for a in assets if a.get("name") == "nexus_mcp.zip"]
        if zip_assets:
            asset_url = zip_assets[0].get("browser_download_url")
            asset_size = zip_assets[0].get("size")
            print(f"GitHub Actions successfully attached nexus_mcp.zip ({asset_size} bytes): {asset_url}")
            workflow_completed = True
            break
        else:
            print(f"Waiting for release.yml workflow... ({i+1} * 5s)")

if not workflow_completed:
    print("Warning: GitHub Actions workflow is still running. Check https://github.com/VictorCV-DAM/ha-nexus-mcp/actions")
else:
    print("Release v1.5.4 successfully created and packaged by GitHub Actions!")
