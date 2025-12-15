# Selise Blocks LMT

Selise Blocks LMT (Logging, Monitoring, and Tracing) library for Selise Blocks applications.
It sends logs and traces to Azure Service Bus for centralized processing.

---

## Installation

Using pip:

```bash
pip install seliseblocks-lmt
```

Using uv:

```bash
uv add seliseblocks-lmt
```

Add to `pyproject.toml`:

```toml
[project]
dependencies = [
    "seliseblocks-lmt>=0.0.1",
]
```

---


## Complete Example

```python
import logging
from fastapi import FastAPI, Request
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from blocks_lmt.log_config import configure_logger
from blocks_lmt.tracing import configure_tracing
from blocks_lmt.activity import Activity

app = FastAPI(title="Example Service with LMT")
FastAPIInstrumentor.instrument_app(app)

configure_logger(
    x_blocks_key="default-tenant",
    blocks_service_id="example-service",
    connection_string="Endpoint=sb://your-namespace.servicebus.windows.net/;..."
)

configure_tracing(
    x_blocks_key="default-tenant",
    blocks_service_id="example-service",
    connection_string="Endpoint=sb://your-namespace.servicebus.windows.net/;..."
)

logger = logging.getLogger(__name__)

@app.get("/")
async def root():
    logger.info("Root endpoint called")
    with Activity.start("handle_root_request") as activity:
        activity.set_property("endpoint", "/")
        return {"message": "Hello World"}

@app.get("/health")
async def health(request: Request):
    Activity.set_current_properties({
        "http.query": str(dict(request.query_params)),
        "http.headers": str(dict(request.headers))
    })
    return {"status": "healthy"}
```

---

## Activity API Reference

### Context Manager

```python
with Activity.start("operation_name") as activity:
    activity.set_property("key", "value")
    activity.set_properties({"key1": "val1", "key2": "val2"})
```

### Status Handling

```python
from opentelemetry.trace import StatusCode

Activity.set_current_status(StatusCode.ERROR, "Error message")
```

---

## Best Practices

1. Always instrument FastAPI:

```python
FastAPIInstrumentor.instrument_app(app)
```

2. Use context managers for activities to ensure proper cleanup:

```python
with Activity.start("operation"):
    ...
```

3. Log inside active spans to maintain trace correlation:

```python
logger.info("This log is trace-correlated")
```

4. Add meaningful properties to activities:

```python
activity.set_property("user_id", user_id)
```

---

## Dependencies

```toml
azure-servicebus = ">=7.14.2"
opentelemetry-api = ">=1.33.1"
opentelemetry-sdk = ">=1.33.1"
opentelemetry-instrumentation-fastapi = ">=0.54b1"
```

