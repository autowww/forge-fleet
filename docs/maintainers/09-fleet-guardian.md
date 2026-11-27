# fleet-guardian

`fleet-guardian` is a separate apt package. It watches one host and talks to local Fleet over HTTP. It does not import `fleet_server`.

## What it records

- Disk bytes from Space Guardian's last run (each run counted once).
- CPU core-seconds and GPU-seconds avoided after a finding clears. These are estimates.
- kWh avoided. A host whose RAPL counter stays at zero keeps `kwh_is_estimate: true`.

Findings exist only while the Fleet job queue and active workers are empty. A warning-or-hotter package temperature, host CPU above `FLEET_GUARDIAN_CPU_PCT` (default 20) from a process outside the idle set, or NVIDIA utilization above `FLEET_GUARDIAN_GPU_PCT` (default 20) becomes a finding. The first action is `notify`.

`always` in Element repeats a closed action: `notify`, `space_tier0`, `space_tier1`, or `stop_unit` for one named user unit. `never` blocks that signature. A small LLM may attach a note when `FLEET_GUARDIAN_LLM_BASE_URL` is set. An unknown action is ignored.

## Rollout order

1. Publish the `fleet-guardian` deb into `https://packages.forgesdlc.com/fleet/ubuntu/` without adding it to the `forge-fleet` Depends line.
2. Install it by name on Mercury and Venus (`package: fleet-guardian` on `POST /v1/admin/upgrade`).
3. Confirm `GET /v1/admin/guardian` on each. Unavailable thermals (Venus) are not a finding. A hot package with an empty queue (Mercury) is notify-only until a lesson says otherwise.
4. Only after both pass, add `Depends: fleet-guardian` and upgrade Granite.

Mercury and Venus passed on `fleet-guardian` 0.1.0 with Fleet 0.3.251 (proxy and package override, no Depends). `forge-fleet` 0.3.252 and `fleet-guardian` 0.1.1 add the Depends line and the mesh digest. They are built into the local apt tree. Granite stays on its current packages until that tree is on `packages.forgesdlc.com`. The Firebase CLI needs `firebase login --reauth` before that deploy.

## API

Fleet proxies `GET /v1/admin/guardian` and `POST /v1/admin/guardian/findings/{id}/decision` to `127.0.0.1:18780`. Granite reads peers through `GET /v1/remote-peers/{id}/admin/guardian`.

Element, in the ops room: `!guardian status` for the cluster, `!guardian status <host>` for one peer, and `!guardian approve|always|never|hold <id>` to answer a finding. The Matrix adapter reads Fleet and posts the decision. It does not start an agent.
