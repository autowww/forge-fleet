# Learn 101 — Onboard with Fleet

**Purpose:** take someone from zero to a **working Fleet** with **`curl`**, a first **`docker_argv`** job, and a pass through **`/admin/`**.

| | |
| --- | --- |
| **Audience** | Developers and operators new to Fleet |
| **Total effort** | **~1–2 hours** end-to-end (faster if Docker + systemd are already familiar) |
| **Prerequisites** | **Python 3.11+**, **git**, and (for jobs) **Docker Engine** on the host |
| **Success** | **`GET /v1/version`** works; **`POST /v1/jobs`** with **`kind: docker_argv`** reaches **`completed`** for **`hello-world`**; you can find the job in **`/admin/`** |

## At a glance

- **You will:** bring up Fleet locally or on a host, verify **`/v1/*`**, finish one **`docker_argv`** lab, and skim **`/admin/`**.
- **Time:** plan **~1–2 hours** if Docker and systemd are unfamiliar.
- **Out of scope:** multi-tenant schedulers and cross-host orchestration — Fleet stays single-host on purpose.

Follow in order unless you already know Docker + Fleet:

1. **[What is Fleet?](01-what-is-fleet.md)** — plain-language scope + concepts + ports
2. **[Install & run locally](02-install-run-local-dev.md)** — dev loop (**venv**, Compose, verification)
3. **[Host bootstrap](03-host-bootstrap.md)** — OS packages (fresh machine / bare metal)
4. **[Install from git](04-git-install.md)** — **`git-install.sh`**, systemd layouts
5. **[Quickstarts (verify)](05-quickstarts.md)** — scripted paths + **`curl`** bundles
6. **[Your first Fleet job](06-first-fleet-job.md)** — **`POST /v1/jobs`** lifecycle lab
7. **[Admin dashboard & Studio](07-admin-dashboard-and-studio.md)** — **`/admin/`** tour + **`LENSES_FLEET_*`**

**Before:** **[Start here](../start/01-start-here.md)** · **After:** **[Build 201](../build-201/README.md)** · **Ops help:** **[Troubleshooting](../operate-301/04-troubleshooting.md)** · **[Security](../operate-301/01-security.md)**
