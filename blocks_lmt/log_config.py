import logging

from blocks_lmt.azure_servicebus_log_exporter import (
    AzureServiceBusHandler,
    TraceContextFilter
)


def configure_logger(
    x_blocks_key: str,
    blocks_service_id: str,
    connection_string: str,
    batch_size: int = 100,
    flush_interval_sec: float = 5.0,
    max_retries: int = 3,
    max_failed_batches: int = 100
):
    """
    Configure the logger to send logs to Azure Service Bus.
    
    Args:
        x_blocks_key: Tenant ID for log isolation
        blocks_service_id: Service identifier
        connection_string: Azure Service Bus connection string
        batch_size: Number of logs to batch before sending (default: 100)
        flush_interval_sec: Interval in seconds to flush logs (default: 5.0)
        max_retries: Maximum number of retries for failed batches (default: 3)
        max_failed_batches: Maximum number of failed batches to queue (default: 100)
    """
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(TenantId)s] [%(TraceId)s] %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    servicebus_handler = AzureServiceBusHandler(
        x_blocks_key=x_blocks_key,
        service_name=blocks_service_id,
        connection_string=connection_string,
        batch_size=batch_size,
        flush_interval_sec=flush_interval_sec,
        max_retries=max_retries,
        max_failed_batches=max_failed_batches
    )

    context_filter = TraceContextFilter(x_blocks_key=x_blocks_key)
    console_handler.addFilter(context_filter)
    servicebus_handler.addFilter(context_filter)

    logger.handlers.clear()
    logger.addHandler(console_handler)
    logger.addHandler(servicebus_handler)
    
    logger.info(f"Logger configured with Azure Service Bus handler (Topic: lmt-{blocks_service_id})")