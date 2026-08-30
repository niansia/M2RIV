# MLflow Model Change Report reference consumer

This integration consumes a Model Change Report bundle without importing the
Merriv Python API.
It first invokes the public `merriv mcr verify --strict` boundary, then records the
report identity, evaluation decision, verification scope, metrics, and complete
bundle in an MLflow run. It records deployment authorization as `not-evaluated`:
MLflow or another consumer-side policy controller remains responsible for an
organization's `ALLOW`/`DENY` decision. The report only records whether its bound
evaluation policy was satisfied.

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
merriv conformance consumer integrations/mlflow_mcr/consumer-receipt.json
```
