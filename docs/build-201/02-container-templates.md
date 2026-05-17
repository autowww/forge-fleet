# Requirement templates and container type catalog

Fleet stores operator-defined **container types** in `etc/containers/types.json` under `--data-dir`. Optional `**requirements[]`** on each type references stable slugs declared in `**etc/containers/requirement_templates.json`**.

Built or pulled **template images** are recorded in `**etc/containers/build_cache.json`** (alongside SQLite). Template builds are a convenience for trusted operator hosts; they are **not** a substitute for sandboxing untrusted workloads (see `01-workspace-upload.md`).

```blueprint-diagram-ascii
key: gate
alt: Template resolve and optional docker build
caption: API resolves requirement ids; Fleet may build or pull images before jobs run.
API request -> resolve fingerprints -> cache hit path
cache miss -> docker build or pull -> updated cache -> job argv inject
```

## Files


| Path                                        | Purpose                                                                                                                       |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `etc/containers/types.json`                 | Categories + types (`id`, `category_id`, `container_class`, `title`, optional `requirements`, optional capability overrides). |
| `etc/containers/requirement_templates.json` | Version + `templates[]`: each row `id`, `title`, `kind` (`dockerfile` \| `image`), `ref`, optional `notes`, optional **`image_semver`** (for `kind: image` only — policy/compare string; **`ref`** remains the pull target). |
| `etc/containers/build_cache.json`           | Cache entries keyed by requirement bundle fingerprint → resolved `image` tag, timestamps, errors.                             |
| `etc/containers/dockerfiles/`               | Recommended location for Dockerfile paths referenced as `ref` (relative to `etc/containers/`).                                |


## Requirement bundles vs builds

**Cache fingerprint:** `GET /v1/container-templates/resolve?requirements=a,b` and `POST /v1/container-templates/build` with multiple **`requirement_ids`** both participate in one **bundle fingerprint** for the **sorted set** of requirement template rows (see **`bundle_fingerprint`** in [`fleet_server/container_templates.py`](../../fleet_server/container_templates.py)).

**What Fleet builds or pulls:** **`run_template_build`** (same module) applies these rules:

- **Single requirement id:** **`kind: dockerfile`** runs **`docker build`** once (build context = the Dockerfile’s parent directory). **`kind: image`** runs **`docker pull`** for that template’s **`ref`**.
- **Multiple requirement ids:** Supported **only** when **every** template is **`kind: image`** and **all share the same `ref`** (effectively one **`docker pull`**). Otherwise Fleet fails with **`multi_requirement_build_supported_only_for_single_dockerfile_or_all_same_image`** — search Fleet logs for that token when debugging failed resolves or builds.

**What Fleet does not do:** Fleet does **not** merge several **`kind: dockerfile`** templates into one runnable image. Encode the full dependency stack (“pre-installed software”) in **one** Dockerfile, register it under **one** requirement template id, **or** publish **one** registry image and reference it with **`kind: image`**.


## Environment variables


| Variable                         | Effect                                                                                                                                                                                                                                                                 |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `FLEET_TEMPLATE_PACKAGE_UPLOAD_MAX_BYTES` | **Default 64 MiB** — max HTTP body for **`PUT /v1/container-templates/{id}/package`**. |
| `FLEET_TEMPLATE_PACKAGE_MAX_UNCOMPRESSED_BYTES` | Extracted bytes limit for template packages (default **120 MiB**). |
| `FLEET_TEMPLATE_PACKAGE_MAX_FILES` | Max regular files in a template archive (default **5000**). |
| `FLEET_TEMPLATE_PACKAGE_MAX_PATH_DEPTH` | Max path depth (default **40**). |
| `FLEET_TEMPLATE_BUILD_NETWORK`   | **Opt-out.** By default Fleet allows Docker’s normal network so `docker build` can pull bases and `kind: image` templates run `docker pull`. Set to `0`, `false`, or `no` to use `docker build --network none` and to **block** `docker pull` for pinned images. |
| `FLEET_PREFETCH_TEMPLATE_IMAGES` | **Opt-out.** By default Fleet starts a **background** prefetch that runs `docker build` / `docker pull` once per declared template ID at process start (errors are logged; the server keeps running). Set to `0`, `false`, or `no` to skip—useful when the catalog is huge and startup latency matters. |
| `FLEET_DOCKER_BIN`               | Override path to the `docker` CLI.                                                                                                                                                                                                                                   |
| `FLEET_DOCKER_BUILDKIT`        | **`1`** / **`true`** — always set `DOCKER_BUILDKIT=1` for `docker build` (fails if `buildx` is missing). **`0`** / **`false`** — always use the legacy builder (`DOCKER_BUILDKIT=0`). **Unset (default)** — try BuildKit first; if Docker reports a **missing or broken buildx** error, Fleet **retries once** with BuildKit off so hosts with Engine-only installs still build. For best performance on modern installs, add the **`docker-buildx-plugin`** package (see Docker docs) and keep this unset. |

## HTTP API (bearer auth when `FLEET_BEARER_TOKEN` is set)


| Method | Path                                                                  | Purpose                                                                                                                                                                                  |
| ------ | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/v1/container-types`                                                 | Read catalog (unchanged shape: categories, types, `types_materialized`).                                                                                                                 |
| PUT    | `/v1/container-types`                                                 | Replace full validated catalog document.                                                                                                                                                  |
| POST   | `/v1/container-types`                                                 | Append one type row (`id` must be new).                                                                                                                                                    |
| PUT    | `/v1/container-types/{id}`                                            | Update one type row.                                                                                                                                                                     |
| DELETE | `/v1/container-types/{id}`                                            | Remove type (`empty` is reserved; blocked if services reference `type_id` or running jobs use `container_class`).                                                                        |
| PUT    | `/v1/container-templates/{requirement_id}/package`                 | **Raw body:** gzip (or plain) **tar** archive. Extracts to `etc/containers/dockerfiles/{id}/` and **upserts** a `kind: dockerfile` row. Query: optional `title`, `notes`, `replace` (`0` / `false` / `no` = refuse if the template and Dockerfile already exist). Optional header **`X-Template-Package-Sha256`** (hex) must match the body. |
| GET    | `/v1/container-templates`                                             | Read requirement templates document + paths.                                                                                                                                            |
| PUT    | `/v1/container-templates`                                             | Replace full requirement templates document (validated).                                                                                                                                |
| GET    | `/v1/container-templates/status`                                      | Build cache JSON + in-process build state.                                                                                                                                               |
| GET    | `/v1/container-templates/resolve?requirements=a,b`                 | Resolve cached image for the requirement set; on cache miss **builds/pulls by default**. Pass `build_if_missing=0` (or `false` / `no`) only when you must skip Docker and accept `not_in_cache`. |
| POST   | `/v1/container-templates/build`                                       | Body `{"requirement_ids":["slug",…]}` — run `docker build` or `docker pull` per rules in `fleet_server/container_templates.py`.                                                             |
| POST   | `/v1/jobs`                                                            | Optional: `meta.use_fleet_template_image`, `meta.requirements`, optional `meta.build_template_if_missing` (defaults **on** unless explicitly `false`, `0`, or the strings `false` / `no`)—resolves image and rewrites the Docker **`run`** image token in `argv` (supports `docker … run` and `docker container run`, and paths whose basename is `docker`). |


## Admin UI

Under **Container types**, operators get a table with **Edit** / **Delete** / **Add type**. Under **Requirement templates**, rows can be edited locally then **Save templates** persists `requirement_templates.json`. **Build requirement bundle** calls `POST /v1/container-templates/build`.

## Argv injection limitations

When `POST /v1/jobs` uses `meta.use_fleet_template_image`, Fleet rewrites the **first image-looking token** after `docker … run` (or `docker container run`) by skipping short and long options. Shapes where the **image immediately follows a short flag without a separate value** (for example `docker run --rm myimage …`) can be parsed incorrectly because `--rm` may consume the next token as its value.

**Recommended argv** for reliable injection: place at least one **`-e NAME=value`** (or another flag that takes a separate argument) between `run` and the image, or put the image as the first non-option token after all flags with explicit values, e.g. `docker run -e FLEET_PLACEHOLDER=1 myimage:tag cmd …`.

## Certificator (or other clients): discover, compare semver, upsert

1. `GET /v1/container-types` — see which `id` / `container_class` / `requirements[]` already exist.
2. `GET /v1/container-templates` — read each template’s **`ref`** and optional **`image_semver`** (for `kind: image`).
3. Compare **`image_semver`** and **`ref`** to your policy; if stale or missing rows, build a full document and `PUT /v1/container-templates`.
4. Optionally `POST /v1/container-templates/build` then `GET /v1/container-templates/resolve?requirements=…` before enqueueing jobs.

Changing **`image_semver`** or **`ref`** for an image template changes the **bundle fingerprint** (cache key), so Fleet treats it as a new resolved bundle after rebuild.

## Remote API E2E (optional)

From a dev machine with Docker + network access to a real Fleet host, you can run **`tests/test_remote_fleet_container_templates_e2e.py`**: it **`GET`s** health, **`PUT`s** a disposable **`kind: image`** template (default **`alpine:3.20`**), **`POST`s** **`/v1/container-templates/build`**, **`GET`s** resolve, **`POST`s** a **`docker_argv`** job with **`meta.use_fleet_template_image`**, polls **`GET /v1/jobs/{id}`**, then restores templates by **`PUT`** without the disposable row.

```bash
export RUN_REMOTE_FLEET_CONTAINER_API_E2E=1
export FORGE_FLEET_BASE_URL=https://your-fleet.example
export FORGE_FLEET_BEARER_TOKEN=...
cd forge-fleet && PYTHONPATH=. python3 -m pytest tests/test_remote_fleet_container_templates_e2e.py -v
```

Unset **`RUN_REMOTE_FLEET_CONTAINER_API_E2E`** (or set **`SKIP_REMOTE_FLEET_CONTAINER_API_E2E=1`**) so CI does not hit production. Optional: **`FLEET_REMOTE_E2E_IMAGE`** to override the pull image.

**Archive layout:** The extracted tree must contain a **`Dockerfile`** at the **root** of the archive, or under **one** top-level directory (e.g. `my_ctx/Dockerfile`). Put **PyPI** / system package install steps in that Dockerfile. **No** certificator template ships inside the `forge-fleet` git tree; publish the reference package from **forge-certificators** (`fleet-container-template/`, `scripts/fleet/package-certificator-template.sh`, or compat `scripts/package-fleet-certificator-template.sh`).

## Troubleshooting: certificator `certificator_source_ingest_worker` template

Forge Fleet **does not** seed a default Dockerfile. On a fresh data directory, **`GET /v1/container-templates`** may list **no** dockerfile rows until you install one.

1. In **forge-certificators**, run **`./scripts/fleet/package-certificator-template.sh`** (or **`./scripts/package-fleet-certificator-template.sh`**) to produce **`certificator_source_ingest_worker.tar.gz`**.
2. Upload: **`PUT /v1/container-templates/certificator_source_ingest_worker/package`** with the archive as the **raw body** and admin bearer auth (optional query **`title`**, **`notes`**, **`replace=1`**).
3. Build: **`POST /v1/container-templates/build`** with **`{"requirement_ids":["certificator_source_ingest_worker"]}`** (needs Docker on the Fleet host and template build network unless opted out).

If **`docker build`** fails, inspect **`GET /v1/container-templates/status`** and Fleet logs. If the Dockerfile references outdated **`git+https://github.com/.../forge-certificators`**, replace it with the package from **forge-certificators** and re-upload.

## Troubleshooting (historical): stale on-disk Dockerfile from git-based pip

Older deployments may still have **`etc/containers/dockerfiles/certificator_source_ingest_worker/Dockerfile`** from manual edits. Replace it by uploading a fresh package (**`PUT …/package`**) or editing files under **`paths.dockerfiles_root`** then **`POST /v1/container-templates/build`**.

## Manual QA (admin)

1. Open `/admin/` with a browser; set bearer in localStorage if your Fleet uses `FLEET_BEARER_TOKEN`.
2. **Container types:** Add a type, edit fields, delete a non-reserved type, Reload.
3. **Requirement templates:** Add row (dockerfile path under `etc/containers/dockerfiles/` or `kind: image` + `ref`), set optional **image_semver**, Save templates, Build bundle, Reload.
4. In devtools Network tab, confirm `PUT` / `POST` / `DELETE` return 2xx and response JSON `ok: true` where applicable.
