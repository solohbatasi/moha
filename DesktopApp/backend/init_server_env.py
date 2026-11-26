"""Create a private server .env with random database and JWT secrets."""

from pathlib import Path
import secrets


root = Path(__file__).resolve().parent
template_path = root / ".env.server.example"
env_path = root / ".env"

if env_path.exists():
    raise SystemExit("Refusing to overwrite existing .env")

contents = template_path.read_text(encoding="utf-8")
replacements = {
    "GENERATE_A_LONG_RANDOM_SECRET": secrets.token_hex(32),
    "GENERATE_A_LONG_RANDOM_PASSWORD": secrets.token_hex(32),
    "GENERATE_ANOTHER_LONG_RANDOM_PASSWORD": secrets.token_hex(32),
}
for placeholder, value in replacements.items():
    contents = contents.replace(placeholder, value)
if "GENERATE_" in contents:
    raise SystemExit("Unresolved secret placeholder in server env template")

env_path.write_text(contents, encoding="utf-8")
env_path.chmod(0o600)
print("Created private .env with random secrets; no values displayed.")
