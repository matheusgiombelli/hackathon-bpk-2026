"""
Finaliza o setup do Teams depois que voce tem o Microsoft App ID.

Uso:
    python setup_teams.py <MICROSOFT_APP_ID> <TUNNEL_URL>

Exemplo:
    python setup_teams.py 12345678-abcd-... https://xyz.trycloudflare.com

O script:
  1. Atualiza manifest.json com o App ID
  2. Recria o zip manifest.zip pronto para upload no Teams
  3. Mostra o que fazer depois
"""
import json
import sys
import zipfile
from pathlib import Path

MANIFEST_DIR = Path("manifest")


def build_zip(app_id: str, tunnel_url: str):
    manifest_path = MANIFEST_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest["bots"][0]["botId"] = app_id
    manifest["validDomains"] = [tunnel_url.replace("https://", "").replace("http://", "")]

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"manifest.json atualizado com botId={app_id}")

    zip_path = MANIFEST_DIR / "manifest.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.write(MANIFEST_DIR / "manifest.json", "manifest.json")
        z.write(MANIFEST_DIR / "icon_color.png",   "icon_color.png")
        z.write(MANIFEST_DIR / "icon_outline.png",  "icon_outline.png")

    print(f"manifest.zip criado em: {zip_path.resolve()}")
    print()
    print("Proximos passos:")
    print("  1. Abra o Teams → Apps → Gerenciar seus apps → Carregar um app")
    print(f"  2. Selecione: {zip_path.resolve()}")
    print("  3. Clique em 'Adicionar' e comece a conversar com o bot")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python setup_teams.py <APP_ID> <TUNNEL_URL>")
        print("Ex:  python setup_teams.py 1234-abcd https://xyz.trycloudflare.com")
        sys.exit(1)

    app_id = sys.argv[1]
    tunnel_url = sys.argv[2]
    build_zip(app_id, tunnel_url)
