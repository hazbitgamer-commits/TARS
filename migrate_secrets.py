"""Move the owner's credentials out of plain text and into the vault.

Before this ran, his SEQTA password, Telegram bot token, Eufy password,
Solax token and Claude token were sitting in readable text in .env and
profile.json. Anything on the PC could read them, the backup copied them,
and only an exclusion list stood between them and a public GitHub repo.

Order matters and is deliberate:

  1. copy the value into Windows Credential Manager
  2. read it back and check it matches, byte for byte
  3. ONLY THEN blank it from the file

A crash anywhere in that sequence leaves the credential in at least one
place. It is never deleted on trust.

    runtime\\python.exe migrate_secrets.py          (dry run — shows the plan)
    runtime\\python.exe migrate_secrets.py --apply  (do it)
"""
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ENV = BASE / ".env"
PROFILE = BASE / "profile.json"

# Anything matching these names in .env is a credential. Deliberately broad:
# a false positive means one extra thing gets encrypted, which is fine.
SECRET_ENV = re.compile(r"(PASS|TOKEN|KEY|SECRET|CREDENTIAL)", re.I)
# ...except these, which are settings that merely LOOK like secrets
NOT_SECRET = {"SEQTA_URL", "SEQTA_USER", "TWILIO_NUMBER", "HOME_CITY",
              "ELEVENLABS_VOICE", "KEYBOARD_LAYOUT"}


def env_secrets() -> dict:
    try:
        lines = ENV.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    found = {}
    for line in lines:
        if "=" not in line or line.strip().startswith("#"):
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if name in NOT_SECRET or not value:
            continue
        if SECRET_ENV.search(name):
            found[name] = value
    return found


def profile_secrets() -> dict:
    import profile

    try:
        data = json.loads(PROFILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: str(v) for k, v in data.items()
            if k in profile.SECRETS and v}


def main() -> int:
    apply = "--apply" in sys.argv
    import profile
    import secrets_store as ss

    from_env = env_secrets()
    from_profile = profile_secrets()
    if not (from_env or from_profile):
        print("Nothing left in plain text — already done.")
        return 0

    print(f"{'MIGRATING' if apply else 'DRY RUN — nothing will change'}\n")
    print(f"In .env         : {', '.join(sorted(from_env)) or 'none'}")
    print(f"In profile.json : {', '.join(sorted(from_profile)) or 'none'}\n")
    if not apply:
        print("Run again with --apply to do it.")
        return 0

    # ---- 1 & 2: copy into the vault, then verify, for every single one
    verified_env, verified_profile = {}, {}
    for name, value in from_env.items():
        ss.put_env(name, value)
        if ss.use_env(name) == value:
            verified_env[name] = value
            print(f"  vaulted + verified  {name}")
        else:
            print(f"  FAILED to vault     {name} — leaving it where it is")
    for key, value in from_profile.items():
        var = profile._env_name(key)
        ss.put_env(var, value)
        if ss.use_env(var) == value:
            verified_profile[key] = var
            print(f"  vaulted + verified  {key} -> {var}")
        else:
            print(f"  FAILED to vault     {key} — leaving it where it is")

    # ---- 3: only now remove the plaintext copies
    if verified_env:
        lines = ENV.read_text(encoding="utf-8", errors="replace").splitlines()
        kept = []
        for line in lines:
            name = line.partition("=")[0].strip()
            if name in verified_env:
                kept.append(f"# {name} moved to Windows Credential Manager")
            else:
                kept.append(line)
        ENV.write_text("\n".join(kept).strip() + "\n", encoding="utf-8")
        print(f"\n  .env: {len(verified_env)} secret(s) removed")

    if verified_profile:
        data = json.loads(PROFILE.read_text(encoding="utf-8"))
        for key in verified_profile:
            data.pop(key, None)
        PROFILE.write_text(json.dumps(data, indent=1), encoding="utf-8")
        print(f"  profile.json: {len(verified_profile)} secret(s) removed")

    print("\nDone. They now live in Windows Credential Manager, tied to your "
          "Windows login.\nRestart TARS so he loads them from there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
