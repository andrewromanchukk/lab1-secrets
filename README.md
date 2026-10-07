# Lab 1: Hardcoded Secrets in Git History

> **This is a self-built security lab, not client work.** All secrets used here are fake and were generated locally. They never had access to any real system.

## Why this lab exists

Many real breaches started with a secret committed to a git repository:

| Incident | What happened |
|---|---|
| **Toyota T-Connect (2017–2022)** | A subcontractor published source code containing a customer-database access key to a public GitHub repo. It stayed exposed for almost five years and affected ~296,000 customers. |
| **Uber (2016)** | An access key sat in a *private* GitHub repo. Attackers logged into GitHub with reused passwords (no MFA), found the key, and pulled data on ~57M people. |
| **DXC Technology (2017)** | AWS keys pushed to a public repo were used to launch 244 VMs in four days, costing ~$64,000. |

The most common reaction to a leaked secret is to delete it in the next commit. **That doesn't remove it.** The secret stays in git history, and anyone with a clone can read it.

This lab reproduces that mistake, detects it, removes it from history, and adds controls so it can't happen again.

## What you'll learn

- Why scanning only the current files gives a false "clean" result
- How to scan full git history with **gitleaks**
- Why default rules aren't enough, and how to close gaps with a custom rule
- How to purge secrets from history with **git-filter-repo**
- Why you **rotate first, then purge**
- How to block secrets before they're committed (pre-commit + CI + GitHub push protection)

## Repository structure

```
.
├── README.md                     # this guide
├── .gitleaks.toml                # gitleaks config: default rules + custom DB-URL rule
├── .pre-commit-config.yaml       # blocks secrets at commit time
├── .github/workflows/
│   └── secret-scan.yml           # blocks secrets in CI
├── .env.example                  # variable names only, no values
├── .gitignore                    # ignores .env
├── app/app.py
└── config/settings.py            # reads secrets from environment variables
```

## Prerequisites

| Tool | Install (macOS) | Tested version |
|---|---|---|
| git | preinstalled | — |
| gitleaks | `brew install gitleaks` | 8.30.0 |
| git-filter-repo | `brew install git-filter-repo` | — |
| pre-commit | `brew install pre-commit` | 4.x |
| openssl | preinstalled | — |

## Safety rules

- Use **only fake secrets**. Never use a real key, even a revoked one.
- Do the reproduce steps in a **local or private** repo.

---

## Step 1. Reproduce the mistake

Create a separate throwaway repo for this step. Don't do it in this repository.

The fake secrets are generated at runtime instead of being written in this README. If this file contained strings that look like real AWS or Stripe keys, GitHub push protection and the pre-commit hook would (correctly) block it.

```bash
mkdir lab1-playground && cd lab1-playground && git init
mkdir app config
echo 'print("hello")' > app/app.py
git add . && git commit -m "init app"

# Generate fake values that match real key formats
rand() { LC_ALL=C tr -dc "$1" </dev/urandom | head -c "$2"; }
FAKE_AWS_ID="AKIA$(rand 'A-Z2-7' 16)"   # real AWS key IDs use base32: A-Z, 2-7
FAKE_AWS_SECRET="$(rand 'A-Za-z0-9' 40)"
FAKE_STRIPE="sk_live_$(rand 'A-Za-z0-9' 48)"
FAKE_DB_PASS="$(rand 'A-Za-z0-9' 16)"
FAKE_DB_URL="postgresql"'://'"app_user:${FAKE_DB_PASS}"'@'"db.internal:5432/shop"

# Commit 2: a developer hardcodes secrets
cat > config/settings.py <<EOF
AWS_ACCESS_KEY_ID = "$FAKE_AWS_ID"
AWS_SECRET_ACCESS_KEY = "$FAKE_AWS_SECRET"
DATABASE_URL = "$FAKE_DB_URL"
STRIPE_SECRET_KEY = "$FAKE_STRIPE"
EOF
openssl genrsa -out config/deploy_key.pem 2048
git add . && git commit -m "add config"

# Commit 3: the "fix" most teams make
cat > config/settings.py <<'EOF'
import os
AWS_ACCESS_KEY_ID = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = os.environ["AWS_SECRET_ACCESS_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]
STRIPE_SECRET_KEY = os.environ["STRIPE_SECRET_KEY"]
EOF
git rm config/deploy_key.pem
git add . && git commit -m "move secrets to env vars"
```

The latest version of the code looks clean. The secrets are still in commit 2.

## Step 2. Detect

```bash
# Current files only
gitleaks dir . --no-banner

# Full history
gitleaks git . --no-banner -v

```

**Expected results:**

| Scan | Result |
|---|---|
| gitleaks, current files | 0 leaks: a **false "clean"** |
| gitleaks, history | 4 leaks: private key, AWS key, AWS secret, Stripe key |

**Takeaways:**
1. Always scan **history**, not just the working tree.
2. **The default rules missed the database password** inside the connection URL. Out-of-the-box rules don't cover every secret format, so check what your stack uses and add rules for it.

## Step 3. Close the gap with a custom rule

This repo's [`.gitleaks.toml`](.gitleaks.toml) extends the default rules with a rule for passwords inside database URLs:

```toml
[extend]
useDefault = true

[[rules]]
id = "db-connection-string-password"
description = "Password inside a database connection URL"
regex = '''(?i)(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^:\s/]+:([^@\s/]{6,})@'''
secretGroup = 1
keywords = ["postgres", "mysql", "mongodb", "redis"]
```

Copy it into the playground repo and rescan:

```bash
gitleaks git . --config .gitleaks.toml --report-format json --report-path before.json
```

Result: **5 leaks**, now including the database password. Keep `before.json` as your "before" evidence.

## Step 4. Fix: rotate first, then purge

### 4.1 Rotate

If a secret was ever pushed anywhere, **treat it as compromised.** Rewriting history doesn't un-leak it: forks, clones, CI caches and automated scanners may already have a copy.

In a real incident, revoke and reissue every exposed credential at its provider **before** cleaning history. In the lab, write down which keys you would rotate and where.

### 4.2 Purge from history

```bash
cp -r . ../lab1-playground-backup

# Remove the private key file from every commit
git filter-repo --force --invert-paths --path config/deploy_key.pem

# Replace the whole hardcoded lines in every commit
cat > ../replacements.txt <<'EOF'
regex:AWS_ACCESS_KEY_ID = ".*"==>AWS_ACCESS_KEY_ID = "REDACTED"
regex:AWS_SECRET_ACCESS_KEY = ".*"==>AWS_SECRET_ACCESS_KEY = "REDACTED"
regex:DATABASE_URL = ".*"==>DATABASE_URL = "REDACTED"
regex:STRIPE_SECRET_KEY = ".*"==>STRIPE_SECRET_KEY = "REDACTED"
EOF
git filter-repo --force --replace-text ../replacements.txt

# Check an old commit
git show HEAD~1:config/settings.py
```

> **Why replace whole lines?** If you replace only the password inside the database URL with a placeholder word, the custom DB-URL rule still matches the placeholder, so the scan never comes back clean.
>
> **Note:** `git filter-repo` removes the `origin` remote on purpose, so you can't accidentally push rewritten history over the original. Re-add it with `git remote add origin <url>`.

### 4.3 Rescan

```bash
gitleaks git . --config .gitleaks.toml -v
```

It should report **no leaks found**.

### 4.4 On a real shared repo

- Force-push all branches and tags.
- Ask every collaborator to re-clone (old clones still contain the secrets).
- Ask GitHub Support to purge cached views of old commits and pull requests if needed.

## Step 5. Prevent it from happening again

### 5.1 Pre-commit hook (local)

[`.pre-commit-config.yaml`](.pre-commit-config.yaml):

```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.30.0
    hooks:
      - id: gitleaks
```

```bash
pre-commit install
```

Test it by trying to commit a file containing a freshly generated fake key (use the `rand` helper from Step 1). The commit should be **blocked**.

### 5.2 CI check (can't be skipped)

Local hooks can be bypassed with `git commit --no-verify`, so CI enforces the same check. [`.github/workflows/secret-scan.yml`](.github/workflows/secret-scan.yml):

```yaml
name: secret-scan
on: [push, pull_request]
permissions:
  contents: read
jobs:
  gitleaks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<full-commit-SHA>   # pin to a SHA, not a tag
        with:
          fetch-depth: 0
      - name: Install gitleaks
        run: |
          curl -sSL https://github.com/gitleaks/gitleaks/releases/download/v8.30.0/gitleaks_8.30.0_linux_x64.tar.gz | tar xz gitleaks
      - name: Scan full history
        run: ./gitleaks git . --config .gitleaks.toml --exit-code 1
```

### 5.3 GitHub push protection

In the repository, go to **Settings → Code security** and turn on **Secret scanning** and **Push protection**. GitHub will then reject pushes that contain known secret formats.

### 5.4 Keep secrets out of code

- Use a `.env` file for local development and list it in [`.gitignore`](.gitignore).
- Commit only [`.env.example`](.env.example), with variable names and no values.
- In production, inject secrets at runtime from a secret store (AWS Secrets Manager, HashiCorp Vault).

---

## Results

| Metric | Before | After |
|---|---|---|
| Secrets in current files | 0 (false "clean") | 0 |
| Secrets in git history (default rules) | 4 | 0 |
| Secrets in git history (default + custom rule) | 5 | 0 |
| Rule coverage | default rules missed the DB password | custom rule covers DB connection strings |
| Time from commit to detection | never | 0 s (blocked at commit) |
| Can a secret reach the remote? | yes | blocked by pre-commit, CI and push protection |

## Key lessons

1. **Deleting a secret in a new commit doesn't remove it.** It lives in history until you rewrite it.
2. **A "clean" working tree proves nothing.** Scan history.
3. **Default rules have gaps.** Add custom rules for the secret formats your stack uses.
4. **Rotate first, purge second.** Once pushed, assume a secret is compromised.
5. **Prevention needs layers:** pre-commit (fast feedback), CI (can't be skipped), push protection (last line of defense).

## References

- [Toyota: access key exposed on GitHub (BleepingComputer)](https://www.bleepingcomputer.com/news/security/toyota-discloses-data-leak-after-access-key-exposed-on-github/)
- [Uber 2016 breach (FTC)](https://www.ftc.gov/business-guidance/blog/2018/04/ftc-addresses-ubers-undisclosed-data-breach-new-proposed-order)
- [DXC AWS keys leak (The Register)](https://www.theregister.com/2017/11/14/dxc_github_aws_keys_leaked/)
- [gitleaks](https://github.com/gitleaks/gitleaks)
- [git-filter-repo](https://github.com/newren/git-filter-repo)
- [GitHub: Removing sensitive data from a repository](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
