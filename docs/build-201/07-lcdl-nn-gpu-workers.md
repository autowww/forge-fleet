# Granite NN worker images (LCDL)

Forge LCDL NN tasks (`nn_fleet_infer`, `nn_train`, `nn_eval`, `nn_generate`) submit **Fleet `docker_argv` workspace jobs** with NVIDIA GPU flags.

## Requirements

- Granite host with NVIDIA Container Toolkit
- Fleet bearer token and `POST /v1/jobs` access
- Worker image with Python 3.11+, TensorFlow GPU for MNIST training

## Images

| Image | Role |
|-------|------|
| `forge-lcdl-nn-infer-worker:local` | Default infer stub / light worker |
| `forge-lcdl-nn-gpu-worker:local` | CUDA MNIST train/eval/infer (`deploy/nn-gpu-worker/Dockerfile`) |

Build GPU worker from forge-lcdl root:

```bash
docker build -f deploy/nn-gpu-worker/Dockerfile -t forge-lcdl-nn-gpu-worker:local .
```

Entry: `python -m forge_lcdl.nn.fleet_worker`

Override with `FORGE_LCDL_NN_FLEET_INFER_IMAGE`.

## Fleet template meta

LCDL sets job meta:

```json
{
  "container_class": "docker_argv_workspace",
  "workspace_upload_required": true,
  "nn_worker_kind": "train",
  "use_fleet_template_image": true,
  "requirements": ["lcdl_nn_gpu_worker"]
}
```

Set `FORGE_LCDL_NN_FLEET_TEMPLATE_REQUIREMENTS=lcdl_nn_gpu_worker` for Granite template resolution.

## docker argv shape

```text
docker run --rm --gpus all <image> python -m forge_lcdl.nn.fleet_worker
```

Workspace tarball contains `request.json` with `op`: `infer` | `train` | `eval` | `generate`.

Worker POSTs `/v1/jobs/{id}/workspace-worker-complete` with `metrics`, `artifact_path`, `device_used`, `architecture`.

## MNIST Granite learning

1. Prepare categorized digits on operator host: `python scripts/prepare-handwritten-digits.py --full`
2. `export FORGE_LCDL_GRANITE_GPU=1`
3. `./scripts/run-mnist-granite-gpu.sh cnn_lenet` or `--full` for all Tier A

## Manual Granite smoke

1. Confirm `/v1/health` reports `host.gpu.nvidia.available: true`
2. `export FORGE_LCDL_TASK_PACKS=nn`
3. Run `nn_fleet_infer` with keras model and `require_gpu: true`
4. Poll job until `completed`; verify `worker_result.device_used` is `GPU`

See [LCDL NN backends](https://github.com/autowww/forge-lcdl/blob/main/docs/guides/NN-BACKENDS.md) in forge-lcdl.
