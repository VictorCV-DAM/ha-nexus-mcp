import os
import subprocess
import json
import urllib.request
import time

os.chdir(r"D:\HITOS - Víctor Antigravity\ha-nexus-mcp")

print("1. Git commit, tag and push v1.6.0...")
subprocess.run(["git", "add", "-A"], check=True)
subprocess.run(["git", "commit", "-m", "chore(release): bump version to v1.6.0 - Hot Helper Creation & Quick Reload"], check=True)
subprocess.run(["git", "tag", "-a", "v1.6.0", "-m", "Release v1.6.0 - HITO: Creacion de Ayudantes en Caliente"], check=True)
subprocess.run(["git", "push", "origin", "main"], check=True)
subprocess.run(["git", "push", "origin", "v1.6.0"], check=True)
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

print("3. Publishing GitHub Release v1.6.0...")
release_title = "v1.6.0 - HITO: Creacion de Ayudantes en Caliente & Recarga Rapida"
release_notes = """## 🚀 Nexus MCP v1.6.0 - HITO: Creación de Ayudantes en Caliente

¡Gran actualización de Nexus MCP tras la aprobación oficial en la tienda de HACS!

### 🌟 Novedades Principales:
- **⚡ Creación de Ayudantes en Caliente (1 Clic):**
  - El asistente de IA ahora puede proponer ayudantes (`input_boolean`, `input_number`, `input_select`, `input_text`, `input_datetime`, `counter`, `timer`, `input_button`) directamente en la tarjeta.
  - La tarjeta Lovelace renderiza un nuevo botón interactivo morado (**"Crear Ayudante en Home Assistant"**).
  - Al pulsar el botón, el ayudante se registra **en caliente** en memoria y en Home Assistant vía WebSocket nativo (`<domain>/create`).
  - **Cero reinicios:** El ayudante aparece inmediatamente disponible para su uso en paneles y automatizaciones, y es 100% editable o eliminable desde *Ajustes > Dispositivos y servicios > Ayudantes*.
- **🔄 Botón de Recarga Rápida:**
  - Añadido un botón muy discreto (`mdi:lightning-bolt-outline`) en la cabecera de la tarjeta Lovelace.
  - Ejecuta la recarga de todas las configuraciones de Home Assistant (`homeassistant.reload_all`) con animación de carga y confirmación visual verde.
- **📦 Reducción de 2.5 MB por instalación:**
  - Siguiendo la recomendación del equipo de HACS (@frenck), se eliminaron los PNG duplicados en la raíz de la integración, manteniendo únicamente los activos requeridos en `brand/`.
- **🏷️ Cache Busting Lovelace:**
  - Recursos web actualizados a `?v=1.6.0` para garantizar que la nueva tarjeta se cargue sin problemas de caché.
"""

rel_payload = {
    "tag_name": "v1.6.0",
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

for i in range(24):
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
    print("Release v1.6.0 successfully published and packaged!")
