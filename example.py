"""
Complete example demonstrating Azure Service Bus LMT implementation.
This example shows how to configure and use the logging and tracing system.
"""

import logging
import time
from fastapi import FastAPI
from blocks_lmt._lmt.log_config import configure_logger
from blocks_lmt._lmt.tracing import configure_tracing
from blocks_lmt._lmt.activity import Activity

# ============================================================================
# STEP 1: Configure LMT System
# ============================================================================

# Option A: Use defaults from blocks_secret
configure_logger()
configure_tracing(blocks_service_id="example-service")

# Option B: Provide explicit configuration
"""
configure_logger(
    service_name="example-service",
    connection_string="Endpoint=sb://your-namespace.servicebus.windows.net/;SharedAccessKeyName=...",
    batch_size=100,
    flush_interval_sec=5.0,
    max_retries=3,
    max_failed_batches=100
)

configure_tracing(
    blocks_service_id="example-service",
    connection_string="Endpoint=sb://your-namespace.servicebus.windows.net/;SharedAccessKeyName=...",
    batch_size=1000,
    flush_interval=5.0,
    max_retries=3,
    max_failed_batches=100
)
"""

# ============================================================================
# STEP 2: Create FastAPI Application
# ============================================================================

app = FastAPI(title="Example Service with LMT")

# Get logger
logger = logging.getLogger(__name__)


# ============================================================================
# STEP 3: Use Logging and Tracing
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Application startup event."""
    logger.info("Application starting up")
    
    with Activity.start("startup_initialization") as activity:
        activity.set_property("service", "example-service")
        logger.info("Initializing application components")
        # Simulate initialization
        time.sleep(0.1)


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown event."""
    logger.info("Application shutting down")
    # The system automatically flushes pending logs and traces


@app.get("/")
async def root():
    """Root endpoint demonstrating logging and tracing."""
    logger.info("Root endpoint called")
    
    with Activity.start("handle_root_request") as activity:
        activity.set_property("endpoint", "/")
        activity.set_property("method", "GET")
        
        logger.info("Processing root request")
        
        return {"message": "Hello World"}


@app.get("/users/{user_id}")
async def get_user(user_id: str):
    """
    User endpoint demonstrating nested activities.
    """
    logger.info(f"Get user endpoint called for user_id: {user_id}")
    
    with Activity.start("handle_get_user") as activity:
        # Set baggage for tenant isolation
        activity.set_property("user_id", user_id)
        activity.set_property("endpoint", f"/users/{user_id}")
        
        logger.info(f"Processing get user request for {user_id}")
        
        # Simulate nested operation
        user_data = _fetch_user_from_database(user_id)
        
        # Simulate processing
        processed_data = _process_user_data(user_data)
        
        logger.info(f"Successfully retrieved user {user_id}")
        
        return processed_data


def _fetch_user_from_database(user_id: str) -> dict:
    """
    Simulate database fetch with nested activity.
    """
    with Activity.start("database_query") as activity:
        activity.set_property("operation", "SELECT")
        activity.set_property("table", "users")
        activity.set_property("user_id", user_id)
        
        logger.debug(f"Querying database for user {user_id}")
        
        # Simulate database query
        time.sleep(0.05)
        
        user_data = {
            "id": user_id,
            "name": "John Doe",
            "email": "john@example.com"
        }
        
        activity.set_property("rows_returned", 1)
        
        return user_data


def _process_user_data(user_data: dict) -> dict:
    """
    Simulate data processing with nested activity.
    """
    with Activity.start("process_user_data") as activity:
        activity.set_property("user_id", user_data["id"])
        
        logger.debug(f"Processing user data for {user_data['id']}")
        
        # Simulate processing
        time.sleep(0.02)
        
        processed = {
            **user_data,
            "processed_at": time.time(),
        }
        
        return processed


@app.post("/orders")
async def create_order(order_data: dict):
    """
    Order creation endpoint demonstrating error handling and tracing.
    """
    logger.info("Create order endpoint called")
    
    with Activity.start("handle_create_order") as activity:
        activity.set_property("endpoint", "/orders")
        activity.set_property("method", "POST")
        
        try:
            logger.info(f"Processing order creation")
            
            # Validate order
            with Activity.start("validate_order") as validate_activity:
                validate_activity.set_property("order_items", len(order_data.get("items", [])))
                
                if not order_data.get("items"):
                    raise ValueError("Order must contain at least one item")
                
                logger.debug("Order validation passed")
            
            # Create order in database
            with Activity.start("save_order") as save_activity:
                save_activity.set_property("operation", "INSERT")
                save_activity.set_property("table", "orders")
                
                # Simulate database save
                time.sleep(0.1)
                order_id = "order-12345"
                
                save_activity.set_property("order_id", order_id)
                logger.info(f"Order created successfully: {order_id}")
            
            return {
                "order_id": order_id,
                "status": "created",
            }
            
        except ValueError as e:
            logger.error(f"Order validation failed: {e}")
            activity.set_status(StatusCode.ERROR, str(e))
            raise
        except Exception as e:
            logger.error(f"Unexpected error creating order: {e}", exc_info=True)
            activity.set_status(StatusCode.ERROR, str(e))
            raise


@app.get("/health")
async def health_check():
    """Health check endpoint (minimal logging)."""
    return {"status": "healthy"}


# ============================================================================
# STEP 4: Standalone Function Example (without FastAPI)
# ============================================================================

def standalone_function_example():
    """
    Example showing how to use LMT in standalone functions.
    """
    logger.info("Starting standalone function")
    
    
    with Activity.start("standalone_operation") as activity:
        activity.set_property("function", "standalone_function_example")
        
        logger.info("Performing standalone operation")
        
        # Nested activity
        with Activity.start("nested_operation") as nested:
            nested.set_property("step", 1)
            logger.debug("Executing nested operation")
            time.sleep(0.05)
        
        logger.info("Standalone operation completed")


# ============================================================================
# STEP 5: Error Handling Example
# ============================================================================

def error_handling_example():
    """
    Example showing error handling with LMT.
    """
    logger.info("Starting error handling example")
    
    with Activity.start("error_handling_operation") as activity:
        try:
            logger.info("Attempting operation that will fail")
            
            # Simulate error
            raise RuntimeError("Simulated error for demonstration")
            
        except RuntimeError as e:
            # The activity automatically records the exception in __exit__
            logger.error(f"Operation failed: {e}", exc_info=True)
            # Activity status is automatically set to ERROR
            raise


# ============================================================================
# STEP 6: Manual Activity
# ============================================================================

def manual_activity_example():
    """
    Example showing manual activity.
    """
    logger.info("Starting manual activity example")
    
    # Start activity manually
    activity = Activity.start("manual_operation")
    activity.set_property("mode", "manual")
    
    try:
        logger.info("Performing manual operation")
        time.sleep(0.05)
        
        # Set properties during operation
        activity.set_property("result", "success")
        
        logger.info("Manual operation completed")
        
    except Exception as e:
        activity.record_exception(e)
        activity.set_status(StatusCode.ERROR, str(e))
        logger.error(f"Manual operation failed: {e}", exc_info=True)
        raise
    finally:
        # Must manually stop the activity
        activity.stop()


# ============================================================================
# STEP 7: Static Methods Example
# ============================================================================

def static_methods_example():
    """
    Example showing use of Activity static methods.
    """
    logger.info("Starting static methods example")
    
    with Activity.start("static_methods_operation") as activity:
        # Get current trace IDs
        trace_id = Activity.get_trace_id()
        span_id = Activity.get_span_id()
        
        logger.info(f"Current trace: {trace_id}, span: {span_id}")
        
        # Set properties on current span without holding activity reference
        Activity.set_current_property("custom_attribute", "custom_value")
        Activity.set_current_properties({
            "attribute1": "value1",
            "attribute2": "value2"
        })
        
        logger.info("Static methods example completed")


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    # Run examples
    print("=" * 80)
    print("Running LMT Examples")
    print("=" * 80)
    
    # Run standalone examples
    standalone_function_example()
    static_methods_example()
    
    try:
        error_handling_example()
    except RuntimeError:
        print("Error handling example completed (error expected)")
    
    try:
        manual_activity_example()
    except:
        pass
    
    print("\n" + "=" * 80)
    print("Starting FastAPI application...")
    print("=" * 80)
    print("\nTest endpoints:")
    print("  - GET  http://localhost:8000/")
    print("  - GET  http://localhost:8000/users/123")
    print("  - POST http://localhost:8000/orders")
    print("  - GET  http://localhost:8000/health")
    print("\nLogs and traces will be sent to Azure Service Bus:")
    print(f"  Topic: lmt-example-service")
    print(f"  Subscriptions: blocks-lmt-service-logs, blocks-lmt-service-traces")
    print("=" * 80 + "\n")
    
    # Start FastAPI server
    uvicorn.run(app, host="0.0.0.0", port=8000)