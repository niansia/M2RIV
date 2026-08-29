# MLflow MCR reference consumer

This integration consumes an MCR bundle without importing the M2RIV Python API.
It first invokes the public `m2riv mcr verify --strict` boundary, then records the
report identity, decision, verification scope, metrics, and complete bundle in an
MLflow run. MLflow remains the experiment/registry system; MCR remains the
portable release-evidence contract.

```console
python integrations/mlflow_mcr/consume.py runs/release \
  --experiment deployable-model-releases
```

Use `--dry-run` to print the exact tags, metrics, and artifacts without importing
or contacting MLflow. This is wiring evidence only, not proof that an MLflow
server accepted the run.

The same program emits a deterministic consumer-conformance receipt:

```console
python integrations/mlflow_mcr/consume.py --emit-conformance-receipt \
  examples/mcr_conformance integrations/mlflow_mcr/consumer-receipt.json
m2riv conformance consumer integrations/mlflow_mcr/consumer-receipt.json
```
