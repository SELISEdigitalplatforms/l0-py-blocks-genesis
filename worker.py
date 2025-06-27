import asyncio
import logging
import sys

from api import AiMessage
from blocks_genesis._core.worker import WorkerConsoleApp
from blocks_genesis._message.message_configuration import AzureServiceBusConfiguration, MessageConfiguration
from blocks_genesis._message.event_registry import register_consumer


logger = logging.getLogger(__name__)
message_config = MessageConfiguration(
    azure_service_bus_configuration=AzureServiceBusConfiguration(
        queues=["ai_queue", "ai_queue_2nd"],
        topics=[]
    )
)


def main():
    app = WorkerConsoleApp("blocks_ai_worker", message_config)

    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.exception("\n👋 Graceful shutdown by user")
    except Exception as e:
        logger.exception(f"💥 Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
    
    
@register_consumer("AiMessage")
def handle_user_created_event(event_data: AiMessage):
    print(f"Handling user created event: {event_data}")
