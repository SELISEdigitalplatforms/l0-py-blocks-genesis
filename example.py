"""
Complete example demonstrating Azure Service Bus LMT implementation.
This example shows how to configure and use the logging and tracing system.
"""

import logging
import time
from fastapi import FastAPI, Request
from blocks_lmt.log_config import configure_logger
from blocks_lmt.tracing import configure_tracing
from blocks_lmt.activity import Activity
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# ============================================================================
# STEP 1: Configure LMT System
# ============================================================================

configure_logger(
    x_blocks_key="your-x-blocks-key",
    blocks_service_id="your-service-id",
    connection_string="your-connection-string",
    batch_size=100,
    flush_interval_sec=5.0,
    max_retries=3,
    max_failed_batches=100
)

configure_tracing(
    x_blocks_key="your-x-blocks-key",
    blocks_service_id="your-service-id",
    connection_string="your-connection-string",
    batch_size=100,
    flush_interval=5.0,
    max_retries=3,
    max_failed_batches=100
)



# ============================================================================
# STEP 2: Create FastAPI Application
# ============================================================================

app = FastAPI(title="Example Service with LMT")

FastAPIInstrumentor.instrument_app(app)

# Get logger
logger = logging.getLogger(__name__)




@app.get("/")
async def root():
    """Root endpoint demonstrating logging and tracing."""
    logger.info("Root endpoint called")
    
    with Activity.start("handle_root_request") as activity:
        activity.set_property("endpoint", "/")
        activity.set_property("method", "GET")
        
        logger.info("Processing root request")
        
        return {"message": "Hello World"}

@app.get("/health")
async def health_check(request: Request):
    logger.info(f"Health check endpoint called: {request}")
    """Health check endpoint (minimal logging)."""
    Activity.set_current_properties({
                "http.query": str(dict(request.query_params)),
                "http.headers": str(dict(request.headers))
            })
    return {"status": "healthy"}
