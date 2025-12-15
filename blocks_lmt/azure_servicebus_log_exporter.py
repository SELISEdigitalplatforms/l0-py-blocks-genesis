import logging
import threading
import asyncio
import json
from datetime import datetime, timedelta, timezone
from queue import Queue, Empty
from typing import Dict, List, Optional
from collections import deque
from dataclasses import dataclass, asdict
from azure.servicebus.aio import ServiceBusClient, ServiceBusSender
from azure.servicebus import ServiceBusMessage
import uuid

from blocks_lmt.activity import Activity


@dataclass
class LogData:
    """Represents a log entry to be sent to Azure Service Bus."""
    Timestamp: str
    Level: str
    Message: str
    Exception: str
    ServiceName: str
    Properties: Dict[str, object]
    TenantId: str


@dataclass
class FailedLogBatch:
    """Represents a failed log batch for retry."""
    Logs: List[LogData]
    RetryCount: int
    NextRetryTime: datetime


class LmtServiceBusSender:
    """
    Handles sending logs and traces to Azure Service Bus with retry logic.
    Mirrors the C# LmtServiceBusSender implementation.
    """
    
    def __init__(
        self,
        service_name: str,
        connection_string: str,
        max_retries: int = 3,
        max_failed_batches: int = 100
    ):
        self._service_name = service_name
        self._max_retries = max_retries
        self._max_failed_batches = max_failed_batches
        
        self._failed_log_batches: deque[FailedLogBatch] = deque()
        self._retry_lock = asyncio.Lock()

        self._client: Optional[ServiceBusClient] = None
        self._sender: Optional[ServiceBusSender] = None
        
        if connection_string:
            self._connection_string = connection_string
            self._topic_name = self._get_topic_name(service_name)
        else:
            print("Service Bus connection string not provided")
            
        # Start retry timer (runs every 30 seconds)
        self._retry_timer = None
        self._stop_event = threading.Event()
        self._start_retry_timer()
    
    @staticmethod
    def _get_topic_name(service_name: str) -> str:
        """Get the topic name for the service (lmt-{service_name})."""
        return f"lmt-{service_name}"
    
    async def _ensure_sender(self):
        """Ensure the Service Bus sender is initialized."""
        if self._sender is None and hasattr(self, '_connection_string'):
            self._client = ServiceBusClient.from_connection_string(self._connection_string)
            self._sender = self._client.get_topic_sender(self._topic_name)
    
    async def send_logs_async(self, logs: List[LogData], retry_count: int = 0):
        """
        Send logs to Azure Service Bus with retry logic.
        """
        await self._ensure_sender()
        
        if self._sender is None:
            print("Service Bus sender not initialized")
            return
        
        current_retry = 0
        
        while current_retry <= self._max_retries:
            try:
                payload = {
                    "Type": "logs",
                    "ServiceName": self._service_name,
                    "Data": [asdict(log) for log in logs]
                }
                
                json_payload = json.dumps(payload, default=str)
                timestamp = datetime.now(timezone.utc)
                message_id = f"logs_{self._service_name}_{timestamp.strftime('%Y%m%d%H%M%S%f')[:-3]}_{uuid.uuid4().hex}"

                message = ServiceBusMessage(
                    body=json_payload,
                    content_type="application/json",
                    message_id=message_id,
                    correlation_id="blocks-lmt-service-logs",
                    application_properties={
                        "serviceName": self._service_name,
                        "timestamp": timestamp.isoformat(),
                        "source": "LogsSender",
                        "type": "logs"
                    }
                )
                
                await self._sender.send_messages(message)
                return
                
            except Exception as ex:
                print(f"Exception sending logs to Service Bus: {ex}, Retry: {current_retry}/{self._max_retries}")
            
            current_retry += 1
            
            if current_retry <= self._max_retries:
                # Exponential backoff: 2^(retry-1) seconds
                delay = 2 ** (current_retry - 1)
                await asyncio.sleep(delay)
        
        # Queue for later retry if all retries failed
        if len(self._failed_log_batches) < self._max_failed_batches:
            failed_batch = FailedLogBatch(
                Logs=logs,
                RetryCount=retry_count + 1,
                NextRetryTime=datetime.now(timezone.utc) + timedelta(minutes=2 ** retry_count)
            )
            self._failed_log_batches.append(failed_batch)
            print(f"Queued log batch for later retry. Failed batches in queue: {len(self._failed_log_batches)}")
        else:
            print(f"Failed log batch queue is full ({self._max_failed_batches}). Dropping batch.")
    
    def _start_retry_timer(self):
        """Start background thread for retrying failed batches every 30 seconds."""
        def retry_worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            while not self._stop_event.is_set():
                try:
                    loop.run_until_complete(self._retry_failed_batches_async())
                except Exception as ex:
                    print(f"Error in retry worker: {ex}")
                
                # Wait 30 seconds before next retry
                self._stop_event.wait(30)
            
            loop.close()
        
        self._retry_timer = threading.Thread(target=retry_worker, daemon=True)
        self._retry_timer.start()
    
    async def _retry_failed_batches_async(self):
        """Retry failed log batches that are ready for retry."""
        async with self._retry_lock:
            now = datetime.now(timezone.utc)
            batches_to_retry = []
            batches_to_requeue = []
            
            # Dequeue all batches
            while self._failed_log_batches:
                failed_batch = self._failed_log_batches.popleft()
                if failed_batch.NextRetryTime <= now:
                    batches_to_retry.append(failed_batch)
                else:
                    batches_to_requeue.append(failed_batch)
            
            # Requeue batches not ready for retry
            for batch in batches_to_requeue:
                self._failed_log_batches.append(batch)
            
            # Retry ready batches
            for failed_batch in batches_to_retry:
                if failed_batch.RetryCount >= self._max_retries:
                    print(f"Log batch exceeded max retries ({self._max_retries}). Dropping batch with {len(failed_batch.Logs)} logs.")
                    continue
                
                print(f"Retrying failed log batch (Attempt {failed_batch.RetryCount + 1}/{self._max_retries})")
                await self.send_logs_async(failed_batch.Logs, failed_batch.RetryCount)
    
    async def close(self):
        """Close the Service Bus client and flush remaining batches."""
        self._stop_event.set()
        if self._retry_timer:
            self._retry_timer.join(timeout=5)
        
        # Retry remaining failed batches
        await self._retry_failed_batches_async()
        
        if self._sender:
            await self._sender.close()
        if self._client:
            await self._client.close()


class AzureServiceBusLogBatcher:
    """
    Batches logs and sends them to Azure Service Bus.
    Mirrors the C# BlocksLogger implementation.
    """
    
    def __init__(
        self,
        x_blocks_key: str,
        service_name: str,
        connection_string: str,
        batch_size: int = 100,
        flush_interval_sec: float = 5.0,
        max_retries: int = 3,
        max_failed_batches: int = 100
    ):
        self.batch_size = batch_size
        self.flush_interval_sec = flush_interval_sec
        self.service_name = service_name
        self.x_blocks_key = x_blocks_key
        
        # Initialize sender
        self._sender = LmtServiceBusSender(
            service_name=service_name,
            connection_string=connection_string,
            max_retries=max_retries,
            max_failed_batches=max_failed_batches
        )
        
        self.queue = Queue()
        self._stop_event = threading.Event()
        self._semaphore = threading.Semaphore(1)
        
        # Start background worker
        self.worker_thread = threading.Thread(target=self._background_worker, daemon=True)
        self.worker_thread.start()
    
    def enqueue(self, record: logging.LogRecord):
        """Add a log record to the queue."""
        log_data = LogData(
            Timestamp=datetime.now(timezone.utc).isoformat(),
            Level=record.levelname,
            Message=record.getMessage(),
            Exception=str(record.exc_info[1]) if record.exc_info else "",
            ServiceName=self.service_name,
            Properties={
                "LoggerName": record.name,
                "TraceId": getattr(record, 'TraceId', None) or Activity.get_trace_id(),
                "SpanId": getattr(record, 'SpanId', None) or Activity.get_span_id(),
            },
            TenantId=getattr(record, 'TenantId', self.x_blocks_key)
        )
        
        self.queue.put(log_data)
    
    def _background_worker(self):
        """Background worker that batches and flushes logs."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        batch = []
        
        while not self._stop_event.is_set():
            try:
                # Try to get a log with timeout
                log_data = self.queue.get(timeout=self.flush_interval_sec)
                batch.append(log_data)
                
                # Try to fill batch up to batch_size
                while len(batch) < self.batch_size:
                    try:
                        log_data = self.queue.get_nowait()
                        batch.append(log_data)
                    except Empty:
                        break
                
            except Empty:
                pass
            
            # Flush batch if it has data
            if batch:
                with self._semaphore:
                    try:
                        loop.run_until_complete(self._sender.send_logs_async(batch))
                    except Exception as e:
                        print(f"[AzureServiceBusLogBatcher] Send error: {e}")
                    finally:
                        batch.clear()
        
        # Flush remaining logs on shutdown
        if batch:
            with self._semaphore:
                try:
                    loop.run_until_complete(self._sender.send_logs_async(batch))
                except Exception as e:
                    print(f"[AzureServiceBusLogBatcher] Send error on shutdown: {e}")
        
        loop.run_until_complete(self._sender.close())
        loop.close()
    
    def stop(self):
        """Stop the background worker and flush remaining logs."""
        self._stop_event.set()
        self.worker_thread.join(timeout=10)


class AzureServiceBusHandler(logging.Handler):
    """
    Logging handler that sends logs to Azure Service Bus.
    Mirrors the C# BlocksLogger integration with logging framework.
    """
    
    _log_batcher: Optional[AzureServiceBusLogBatcher] = None
    
    def __init__(
        self,
        x_blocks_key: str,
        service_name: str,
        connection_string: str,
        batch_size: int = 100,
        flush_interval_sec: float = 5.0,
        max_retries: int = 3,
        max_failed_batches: int = 100
    ):
        super().__init__()
        
        # Create singleton batcher
        if not AzureServiceBusHandler._log_batcher:
            AzureServiceBusHandler._log_batcher = AzureServiceBusLogBatcher(
                x_blocks_key=x_blocks_key,
                service_name=service_name,
                connection_string=connection_string,
                batch_size=batch_size,
                flush_interval_sec=flush_interval_sec,
                max_retries=max_retries,
                max_failed_batches=max_failed_batches
            )
        
        self.log_batcher = AzureServiceBusHandler._log_batcher
    
    def emit(self, record: logging.LogRecord):
        """Emit a log record to the batcher."""
        try:
            self.log_batcher.enqueue(record)
        except Exception:
            self.handleError(record)


class TraceContextFilter(logging.Filter):
    """
    Filter that adds trace context to log records.
    """
    def __init__(self, x_blocks_key: str):
        super().__init__()
        self.tenant_id = x_blocks_key
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Add trace context to log records."""
        if self.tenant_id and not hasattr(record, 'TenantId'):
            record.TenantId = self.tenant_id
        elif not hasattr(record, 'TenantId'):
            record.TenantId = "miscellaneous"

        record.TraceId = Activity.get_trace_id()
        record.SpanId = Activity.get_span_id()
        
        return True