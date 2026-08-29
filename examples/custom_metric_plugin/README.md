# Explicit custom metric plugin
M2RIV deliberately does not scan and import arbitrary Python entry points. Trusted
host code imports a plugin and registers it explicitly:

```python
from m2riv.plugins import builtin_metric_registry
from length_metric import register

registry = builtin_metric_registry()
register(registry)

metrics = registry.metrics()
metric_plugins = registry.metric_plugin_records()
```

Pass both values to `compare_release(...)`. The compiled release plan records the
plugin name, version, capabilities, and non-secret config fingerprint. A duplicate
metric ID or conflicting plugin identity fails before model execution.

The host is responsible for deciding that imported plugin code is trusted. Run
third-party code inside a restricted worker when that trust is not available.
