# Selise Blocks LMT

**Logging, Monitoring, and Tracing** library for Selise Blocks applications. Sends logs and traces to Azure Service Bus for centralized processing.

## Installation

```bash
# Using uv
uv add seliseblocks-lmt

# Using pip
pip install seliseblocks-lmt
```

Add to `pyproject.toml`:
```toml
[project]
dependencies = [
    "seliseblocks-lmt>=0.0.1",
]
```

## Quick Start

```python
from fastapi import FastAPI
from blocks_lmt.log_config import configure_logger
from blocks_lmt.tracing import configure_tracing

app = FastAPI()

# Configure LMT on application startup
configure_logger(
    x_blocks_key="x_blocks_key",
    blocks_service_id="my-service",
    connection_string="Endpoint=sb://your-namespace.servicebus.windows.net/;..."
)

configure_tracing(
    app=app,  # Pass FastAPI app - auto-instruments all HTTP requests
    x_blocks_key="x_blocks_key",
    blocks_service_id="my-service",
    connection_string="Endpoint=sb://your-namespace.servicebus.windows.net/;..."
)
```

**That's it!** All HTTP requests are automatically traced, and logging works everywhere.

## Configuration

### Required Parameters

```python
configure_logger(
    x_blocks_key="x_blocks_key",           # Tenant ID for log isolation
    blocks_service_id="my-service",      # Service identifier
    connection_string="Endpoint=sb://...", # Azure Service Bus connection string
)

configure_tracing(
    app=app,                             # FastAPI application instance
    x_blocks_key="x_blocks_key",           # Tenant ID for trace isolation
    blocks_service_id="my-service",      # Service identifier
    connection_string="Endpoint=sb://...", # Azure Service Bus connection string
)
```

### Optional Parameters

```python
configure_logger(
    x_blocks_key="x_blocks_key",
    blocks_service_id="my-service",
    connection_string="Endpoint=sb://...",
    batch_size=100,           # Logs per batch (default: 100)
    flush_interval_sec=5.0,   # Flush interval (default: 5.0)
    max_retries=3,            # Max retry attempts (default: 3)
    max_failed_batches=100    # Max failed batches to queue (default: 100)
)

configure_tracing(
    app=app,
    x_blocks_key="x_blocks_key",
    blocks_service_id="my-service",
    connection_string="Endpoint=sb://...",
    batch_size=1000,          # Traces per batch (default: 1000)
    flush_interval=5.0,       # Flush interval (default: 5.0)
    max_retries=3,
    max_failed_batches=100
)
```

## Usage

### Automatic HTTP Tracing

**No code needed!** Once configured, all HTTP requests are automatically traced:

```python
from fastapi import FastAPI
from blocks_lmt.tracing import configure_tracing

app = FastAPI()

configure_tracing(app=app, x_blocks_key="x_blocks_key", ...)

# This endpoint is automatically traced!
@app.get("/users/{user_id}")
async def get_user(user_id: str):
    return {"user_id": user_id}
```

Each request automatically gets:
- Trace ID
- Span ID  
- HTTP method, path, status code
- Request duration
- Error details (if any)

### Logging

```python
import logging

logger = logging.getLogger(__name__)

logger.info("Application started")
logger.error("An error occurred", exc_info=True)
logger.debug("Debug information")
```

Logs automatically include:
- Tenant ID (`x_blocks_key`)
- Trace ID (from current span)
- Span ID (from current span)
- Timestamp, level, message

### Custom Tracing (Nested Spans)

Add detailed tracing inside your endpoints:

```python
from blocks_lmt.activity import Activity
import logging

logger = logging.getLogger(__name__)

@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    # HTTP request automatically traced by FastAPIInstrumentor
    
    # Add custom nested span for database query
    with Activity.start("fetch_order_from_db") as activity:
        activity.set_property("order_id", order_id)
        activity.set_property("database", "orders_db")
        
        logger.info(f"Fetching order {order_id}")
        # ... database query ...
    
    return {"order_id": order_id}
```

### Multi-Tenant Tracing

Override tenant per request using baggage:

```python
from blocks_lmt.activity import Activity

@app.get("/users/{user_id}")
async def get_user(user_id: str, tenant_id: str):
    
    # Override tenant in trace baggage
    with Activity.start("get_user_operation") as activity:
        activity.set_property("user_id", user_id)
        
        logger.info(f"Fetching user {user_id} for tenant {tenant_id}")
        return {"user_id": user_id, "tenant_id": tenant_id}
```

## Complete Example

```python
import logging
from fastapi import FastAPI, HTTPException
from blocks_lmt.log_config import configure_logger
from blocks_lmt.tracing import configure_tracing
from blocks_lmt.activity import Activity

# Create FastAPI app
app = FastAPI(title="Order Service")
logger = logging.getLogger(__name__)

# Configure LMT
configure_logger(
    x_blocks_key="default-tenant",
    blocks_service_id="order-service",
    connection_string="Endpoint=sb://your-namespace.servicebus.windows.net/;..."
)

configure_tracing(
    app=app,  # FastAPI auto-instrumentation
    x_blocks_key="default-tenant",
    blocks_service_id="order-service",
    connection_string="Endpoint=sb://your-namespace.servicebus.windows.net/;..."
)

@app.on_event("startup")
async def startup():
    logger.info("Order service starting up")

@app.get("/")
async def root():
    # Automatically traced by FastAPIInstrumentor
    logger.info("Root endpoint called")
    return {"message": "Order Service"}

@app.post("/orders")
async def create_order(order_data: dict, tenant_id: str):
    
    # Custom nested spans
    with Activity.start("create_order_operation") as activity:
        activity.set_property("baggage.TenantId", tenant_id)
        activity.set_property("items_count", len(order_data.get("items", [])))
        
        logger.info(f"Creating order for tenant {tenant_id}")
        
        try:
            # Validate order
            with Activity.start("validate_order") as validate:
                if not order_data.get("items"):
                    raise ValueError("Order must have items")
                validate.set_property("validation_status", "passed")
                logger.debug("Order validation passed")
            
            # Save to database
            with Activity.start("save_order_to_db") as save:
                save.set_property("database", "orders_db")
                # ... database operation ...
                order_id = "order-12345"
                save.set_property("order_id", order_id)
                logger.info(f"Order {order_id} saved successfully")
            
            return {
                "order_id": order_id,
                "status": "created",
                "tenant_id": tenant_id
            }
            
        except ValueError as e:
            logger.error(f"Order validation failed: {e}")
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Azure Service Bus Structure

### Topic
- **Name**: `lmt-{service_id}`
- **Example**: `lmt-order-service`

### Subscriptions
- **Logs**: `blocks-lmt-service-logs`
- **Traces**: `blocks-lmt-service-traces`

### Message Format

**Logs:**
```json
{
  "Type": "logs",
  "ServiceName": "order-service",
  "Data": [
    {
      "Timestamp": "2025-01-15T10:30:00Z",
      "Level": "INFO",
      "Message": "Creating order for tenant x_blocks_key",
      "TenantId": "x_blocks_key",
      "Properties": {
        "TraceId": "abc123...",
        "SpanId": "def456...",
        "LoggerName": "__main__"
      }
    }
  ]
}
```

**Traces:**
```json
{
  "Type": "traces",
  "ServiceName": "order-service",
  "Data": {
    "x_blocks_key": [
      {
        "TraceId": "abc123...",
        "SpanId": "def456...",
        "ParentSpanId": "xyz789...",
        "OperationName": "POST /orders",
        "Kind": "SERVER",
        "Duration": 156.5,
        "Attributes": {
          "http.method": "POST",
          "http.target": "/orders",
          "http.status_code": 200
        },
        "TenantId": "x_blocks_key",
        "Baggage": {
          "TenantId": "x_blocks_key"
        }
      }
    ]
  }
}
```

## Activity API Reference

### Context Manager (Recommended)
```python
with Activity.start("operation_name") as activity:
    activity.set_property("key", "value")
    activity.set_properties({"key1": "val1", "key2": "val2"})
    # Your code here
    # Automatically handles exceptions and cleanup
```

### Manual Management
```python
activity = Activity.start("operation_name")
try:
    activity.set_property("key", "value")
    # Your code here
finally:
    activity.stop()
```

### Static Methods
```python
# Get current trace/span IDs
trace_id = Activity.get_trace_id()
span_id = Activity.get_span_id()

# Set properties on current span
Activity.set_current_property("key", "value")
Activity.set_current_properties({"key1": "value1", "key2": "value2"})

# Set status
from opentelemetry.trace import StatusCode
Activity.set_current_status(StatusCode.ERROR, "Error message")
```

### Get Root Attributes
```python
with Activity.start("operation") as activity:
    # Get single root attribute
    tenant_id = activity.get_root_attribute("TenantId")
    
    # Get all root attributes
    all_attrs = activity.get_all_root_attributes()
```

## Configuration Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `x_blocks_key` | Required | Tenant ID for isolation |
| `blocks_service_id` | Required | Service identifier |
| `connection_string` | Required | Azure Service Bus connection |
| `app` | Required (tracing) | FastAPI app instance |
| `batch_size` | 100 (logs), 1000 (traces) | Batch size before sending |
| `flush_interval_sec` | 5.0 | Flush interval in seconds |
| `max_retries` | 3 | Max retry attempts |
| `max_failed_batches` | 100 | Max failed batches to queue |

## Retry Behavior

### Immediate Retries
On send failure, retries with exponential backoff:
- Retry 1: Wait 1 second
- Retry 2: Wait 2 seconds  
- Retry 3: Wait 4 seconds

### Failed Batch Queue
After max retries, batches are queued and retried every 30 seconds.

## Performance Tuning

### Low Traffic (< 100 req/min)
```python
configure_logger(
    x_blocks_key="x_blocks_key",
    blocks_service_id="service",
    connection_string="...",
    batch_size=50,
    flush_interval_sec=2.0
)
configure_tracing(
    app=app,
    x_blocks_key="x_blocks_key",
    blocks_service_id="service",
    connection_string="...",
    batch_size=500,
    flush_interval=2.0
)
```

### Medium Traffic (100-1000 req/min) - Default
```python
# Use defaults - already optimized
configure_logger(x_blocks_key="...", blocks_service_id="...", connection_string="...")
configure_tracing(app=app, x_blocks_key="...", blocks_service_id="...", connection_string="...")
```

### High Traffic (> 1000 req/min)
```python
configure_logger(
    x_blocks_key="x_blocks_key",
    blocks_service_id="service",
    connection_string="...",
    batch_size=200,
    flush_interval_sec=10.0
)
configure_tracing(
    app=app,
    x_blocks_key="x_blocks_key",
    blocks_service_id="service",
    connection_string="...",
    batch_size=2000,
    flush_interval=10.0
)
```

## Troubleshooting

### Service Bus sender not initialized
**Cause**: Invalid connection string  
**Fix**: Verify `connection_string` parameter

### Messages not appearing in Azure Service Bus
**Cause**: Topic doesn't exist  
**Fix**: Create topic `lmt-{service-name}` with subscriptions

### High failed batch count
**Cause**: Cannot connect to Service Bus  
**Fix**: Check network, authentication, Service Bus status

### Traces showing wrong tenant
**Cause**: Baggage not set  
**Fix**: Use `activity.set_property("baggage.TenantId", tenant_id)`

## Best Practices

1. **Always pass FastAPI app to configure_tracing**
   ```python
   configure_tracing(app=app, ...)  # Enables auto HTTP tracing
   ```

2. **Set x_blocks_key as default tenant**
   ```python
   configure_logger(x_blocks_key="default-tenant", ...)
   ```

3. **Override tenant per request in baggage**
   ```python
   activity.set_property("baggage.TenantId", request_tenant_id)
   ```

4. **Use context managers for activities**
   ```python
   with Activity.start("operation") as activity:
       # Automatically handles cleanup
   ```

5. **Log at appropriate levels**
   - DEBUG: Detailed diagnostic info
   - INFO: General informational messages
   - WARNING: Warning messages
   - ERROR: Error messages
   - CRITICAL: Critical errors

6. **Add meaningful properties to activities**
   ```python
   activity.set_property("user_id", user_id)
   activity.set_property("order_id", order_id)
   activity.set_property("operation_type", "create")
   ```

## Dependencies

```toml
[project.dependencies]
azure-servicebus = ">=7.14.2"
opentelemetry-api = ">=1.33.1"
opentelemetry-sdk = ">=1.33.1"
opentelemetry-instrumentation-fastapi = ">=0.54b1"
```

## What Gets Traced Automatically?

When you pass your FastAPI app to `configure_tracing()`, the following are automatically traced:

✅ All HTTP requests (GET, POST, PUT, DELETE, etc.)  
✅ Request method and path  
✅ Response status code  
✅ Request duration  
✅ Exceptions and errors  
✅ Query parameters  
✅ Route parameters  

You can still add custom nested spans using `Activity.start()` for fine-grained tracing!