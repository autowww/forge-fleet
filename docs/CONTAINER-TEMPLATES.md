# Requirement templates and container type catalog

Fleet stores operator-defined **container types** in `etc/containers/types.json` under `--data-dir`. Optional `**requirements[]`** on each type references stable slugs declared in `**etc/containers/requirement_templates.json`**.

Built or pulled **template images** are recorded in `**etc/containers/build_cache.json`** (alongside SQLite). Template builds are a convenience for trusted operator hosts; they are **not** a substitute for sandboxing untrusted workloads (see `docs/WORKSPACE_UPLOAD.md`).

## Files


| Path                                        | Purpose                                                                                                                       |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `etc/containers/types.json`                 | Categories + types (`id`, `category_id`, `container_class`, `title`, optional `requirements`, optional capability overrides). |
| `etc/containers/requirement_templates.json` | Version + `templates[]`: each row `id`, `title`, `kind` (`dockerfile`                                                         |
| `etc/containers/build_cache.json`           | Cache entries keyed by requirement bundle fingerprint → resolved `image` tag, timestamps, errors.                             |
| `etc/containers/dockerfiles/`               | Recommended location for Dockerfile paths referenced as `ref` (relative to `etc/containers/`).                                |


## Environment variables


| Variable                         | Effect                                                                                                                                                                                                                                                                 |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `FLEET_TEMPLATE_BUILD_NETWORK`   | **Opt-out.** By default Fleet allows Docker’s normal network so `docker build` can pull bases and `kind: image` templates run `docker pull`. Set to `0`, `false`, or `no` to use `docker build --network none` and to **block** `docker pull` for pinned images. |
| `FLEET_PREFETCH_TEMPLATE_IMAGES` | **Opt-out.** By default Fleet starts a **background** prefetch that runs `docker build` / `docker pull` once per declared template ID at process start (errors are logged; the server keeps running). Set to `0`, `false`, or `no` to skip—useful when the catalog is huge and startup latency matters. |
| `FLEET_DOCKER_BIN`               | Override path to the `docker` CLI.                                                                                                                                                                                                                                   |

## HTTP API (bearer auth when `FLEET_BEARER_TOKEN` is set)


| Method | Path                                                                  | Purpose                                                                                                                                                                                  |
| ------ | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/v1/container-types`                                                 | Read catalog (unchanged shape: categories, types, `types_materialized`).                                                                                                                 |
| PUT    | `/v1/container-types`                                                 | Replace full validated catalog document.                                                                                                                                                  |
| POST   | `/v1/container-types`                                                 | Append one type row (`id` must be new).                                                                                                                                                    |
| PUT    | `/v1/container-types/{id}`                                            | Update one type row.                                                                                                                                                                     |
| DELETE | `/v1/container-types/{id}`                                            | Remove type (`empty` is reserved; blocked if services reference `type_id` or running jobs use `container_class`).                                                                        |
| GET    | `/v1/container-templates`                                             | Read requirement templates document + paths.                                                                                                                                            |
| PUT    | `/v1/container-templates`                                             | Replace full requirement templates document (validated).                                                                                                                                |
| GET    | `/v1/container-templates/status`                                      | Build cache JSON + in-process build state.                                                                                                                                               |
| GET    | `/v1/container-templates/resolve?requirements=a,b`                 | Resolve cached image for the requirement set; on cache miss **builds/pulls by default**. Pass `build_if_missing=0` (or `false` / `no`) only when you must skip Docker and accept `not_in_cache`. |
| POST   | `/v1/container-templates/build`                                       | Body `{"requirement_ids":["slug",…]}` — run `docker build` or `docker pull` per rules in `fleet_server/container_templates.py`.                                                             |
| POST   | `/v1/jobs`                                                            | Optional: `meta.use_fleet_template_image`, `meta.requirements`, optional `meta.build_template_if_missing` (defaults **on** unless explicitly `false`, `0`, or the strings `false` / `no`)—resolves image and rewrites the Docker **`run`** image token in `argv` (supports `docker … run` and `docker container run`, and paths whose basename is `docker`). |


## Admin UI

Under **Container types**, operators get a table with **Edit** / **Delete** / **Add type**. Under **Requirement templates**, rows can be edited locally then **Save templates** persists `requirement_templates.json`. **Build requirement bundle** calls `POST /v1/container-templates/build`.
