import threading
import asyncio
import json
from datetime import datetime, timedelta
from queue import Queue, Empty
from typing import Dict, List, Optional
from collections import deque, defaultdict
from dataclasses import dataclass, asdict
from azure.servicebus.aio import ServiceBusClient, ServiceBusSender
from azure.servicebus import ServiceBusMessage
import uuid

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


@dataclass
class TraceData:
    """Represents a trace/span to be sent to Azure Service Bus."""
    Timestamp: str
    TraceId: str
    SpanId: str
    ParentSpanId: str
    ParentId: str
    Kind: str
    ActivitySourceName: str
    OperationName: str
    StartTime: str
    EndTime: str
    Duration: float
    Attributes: Dict[str, object]
    Status: str
    StatusDescription: str
    Baggage: Dict[str, str]
    ServiceName: str
    TenantId: str


@dataclass
class FailedTraceBatch:
    """Represents a failed trace batch for retry."""
    TenantBatches: Dict[str, List[TraceData]]
    RetryCount: int
    NextRetryTime: datetime


class LmtServiceBusTraceSender:
    """
    Handles sending traces to Azure Service Bus with retry logic.
    Mirrors the C# LmtServiceBusSender trace functionality.
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
        
        self._failed_trace_batches: deque[FailedTraceBatch] = deque()
        self._retry_lock = asyncio.Lock()
        
        # Initialize Azure Service Bus client
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
    
    async def send_traces_async(
        self,
        tenant_batches: Dict[str, List[TraceData]],
        retry_count: int = 0
    ):
        """
        Send traces to Azure Service Bus with retry logic.
        Mirrors C# SendTracesAsync method.
        """
        await self._ensure_sender()
        
        if self._sender is None:
            print("Service Bus sender not initialized")
            return
        
        current_retry = 0
        
        while current_retry <= self._max_retries:
            try:
                # Create payload matching C# format
                # Convert TraceData objects to dicts for JSON serialization
                serializable_batches = {
                    tenant_id: [asdict(trace) for trace in traces]
                    for tenant_id, traces in tenant_batches.items()
                }
                
                payload = {
                    "Type": "traces",
                    "ServiceName": self._service_name,
                    "Data": serializable_batches
                }
                
                json_payload = json.dumps(payload, default=str)
                timestamp = datetime.utcnow()
                message_id = f"traces_{self._service_name}_{timestamp.strftime('%Y%m%d%H%M%S%f')[:-3]}_{uuid.uuid4().hex}"
                
                # Create Service Bus message
                message = ServiceBusMessage(
                    body=json_payload,
                    content_type="application/json",
                    message_id=message_id,
                    correlation_id="blocks-lmt-service-traces",
                    application_properties={
                        "serviceName": self._service_name,
                        "timestamp": timestamp.isoformat(),
                        "source": "TracesSender",
                        "type": "traces"
                    }
                )
                
                await self._sender.send_messages(message)
                return
                
            except Exception as ex:
                print(f"Exception sending traces to Service Bus: {ex}, Retry: {current_retry}/{self._max_retries}")
            
            current_retry += 1
            
            if current_retry <= self._max_retries:
                # Exponential backoff: 2^(retry-1) seconds
                delay = 2 ** (current_retry - 1)
                await asyncio.sleep(delay)
        
        # Queue for later retry if all retries failed
        if len(self._failed_trace_batches) < self._max_failed_batches:
            failed_batch = FailedTraceBatch(
                TenantBatches=tenant_batches,
                RetryCount=retry_count + 1,
                NextRetryTime=datetime.utcnow() + timedelta(minutes=2 ** retry_count)
            )
            self._failed_trace_batches.append(failed_batch)
            print(f"Queued trace batch for later retry. Failed batches in queue: {len(self._failed_trace_batches)}")
        else:
            print(f"Failed trace batch queue is full ({self._max_failed_batches}). Dropping batch.")
    
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
        """Retry failed trace batches that are ready for retry."""
        async with self._retry_lock:
            now = datetime.utcnow()
            batches_to_retry = []
            batches_to_requeue = []
            
            # Dequeue all batches
            while self._failed_trace_batches:
                failed_batch = self._failed_trace_batches.popleft()
                if failed_batch.NextRetryTime <= now:
                    batches_to_retry.append(failed_batch)
                else:
                    batches_to_requeue.append(failed_batch)
            
            # Requeue batches not ready for retry
            for batch in batches_to_requeue:
                self._failed_trace_batches.append(batch)
            
            # Retry ready batches
            for failed_batch in batches_to_retry:
                if failed_batch.RetryCount >= self._max_retries:
                    print(f"Trace batch exceeded max retries ({self._max_retries}). Dropping batch.")
                    continue
                
                print(f"Retrying failed trace batch (Attempt {failed_batch.RetryCount + 1}/{self._max_retries})")
                await self.send_traces_async(failed_batch.TenantBatches, failed_batch.RetryCount)
    
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


class AzureServiceBusTraceExporter(SpanExporter):
    """
    OpenTelemetry SpanExporter that sends traces to Azure Service Bus.
    Mirrors the C# LmtTraceProcessor implementation.
    """
    
    def __init__(
        self,
        x_blocks_key: str,
        service_name: str,
        connection_string: str,
        batch_size: int = 1000,
        flush_interval: float = 5.0,
        max_retries: int = 3,
        max_failed_batches: int = 100
    ):
        self._service_name = service_name
        self._x_blocks_key = x_blocks_key
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        
        # Initialize sender
        self._sender = LmtServiceBusTraceSender(
            service_name=service_name,
            connection_string=connection_string,
            max_retries=max_retries,
            max_failed_batches=max_failed_batches
        )
        
        # Queue for batching traces
        self._queue = Queue()
        self._stop_event = threading.Event()
        self._semaphore = threading.Semaphore(1)
        
        # Start background worker
        self._worker_thread = threading.Thread(target=self._run, daemon=True)
        self._worker_thread.start()
    
    def _extract_baggage_from_span(self, span) -> Dict[str, str]:
        """Extract baggage items from span attributes."""
        baggage_items = {}
        
        if hasattr(span, 'attributes') and span.attributes:
            for key, value in span.attributes.items():
                if key.startswith("baggage."):
                    baggage_items[key[8:]] = str(value)
        
        # Use x_blocks_key as default TenantId if not in baggage
        if "TenantId" not in baggage_items:
            baggage_items["TenantId"] = self._x_blocks_key
        
        return baggage_items
    
    def export(self, spans) -> SpanExportResult:
        """
        Export spans to Azure Service Bus.
        Called by OpenTelemetry SDK.
        """
        try:
            for span in spans:
                baggage_items = self._extract_baggage_from_span(span)
                tenant_id = baggage_items.get("TenantId", self._x_blocks_key)
                
                trace_data = self._build_trace_data(span, baggage_items, tenant_id)
                self._queue.put(trace_data)
            
            return SpanExportResult.SUCCESS
        except Exception as ex:
            print(f"[AzureServiceBusTraceExporter] Export failed: {ex}")
            return SpanExportResult.FAILURE
    
    def _build_trace_data(self, span, baggage_items: Dict[str, str], tenant_id: str) -> TraceData:
        """Build TraceData object from OpenTelemetry span."""
        # Build ParentId in W3C trace context format
        if span.parent:
            parent_span_id = format(span.parent.span_id, "016x")
            parent_id = f"00-{format(span.context.trace_id, '032x')}-{parent_span_id}-01"
        else:
            parent_span_id = "0000000000000000"
            parent_id = ""
        
        # Extract attributes (excluding baggage)
        attributes = {}
        if hasattr(span, 'attributes') and span.attributes:
            attributes = {
                k: v for k, v in span.attributes.items()
                if not k.startswith("baggage.")
            }
        
        # Get span kind
        kind = str(span.kind) if hasattr(span, 'kind') else "INTERNAL"
        
        # Calculate timestamps and duration
        start_time = datetime.fromtimestamp(span.start_time / 1_000_000_000)
        end_time = datetime.fromtimestamp(span.end_time / 1_000_000_000)
        duration_ms = (span.end_time - span.start_time) / 1_000_000  # Convert to milliseconds
        
        return TraceData(
            Timestamp=end_time.isoformat(),
            TraceId=format(span.context.trace_id, "032x"),
            SpanId=format(span.context.span_id, "016x"),
            ParentSpanId=parent_span_id,
            ParentId=parent_id,
            Kind=kind,
            ActivitySourceName=span.instrumentation_scope.name if hasattr(span, 'instrumentation_scope') else "",
            OperationName=span.name,
            StartTime=start_time.isoformat(),
            EndTime=end_time.isoformat(),
            Duration=duration_ms,
            Attributes=attributes,
            Status=str(span.status.status_code) if hasattr(span, 'status') else "UNSET",
            StatusDescription=span.status.description if hasattr(span, 'status') and span.status.description else "",
            Baggage=baggage_items,
            ServiceName=self._service_name,
            TenantId=tenant_id
        )
    
    def _run(self):
        """
        Background worker that batches traces by tenant and sends them.
        Mirrors the C# FlushBatchAsync logic.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        tenant_batches: Dict[str, List[TraceData]] = defaultdict(list)
        total_traces = 0
        
        while not self._stop_event.is_set():
            try:
                # Try to get a trace with timeout
                trace_data = self._queue.get(timeout=self._flush_interval)
                tenant_batches[trace_data.TenantId].append(trace_data)
                total_traces += 1
                
                # Try to fill batch up to batch_size
                while total_traces < self._batch_size:
                    try:
                        trace_data = self._queue.get_nowait()
                        tenant_batches[trace_data.TenantId].append(trace_data)
                        total_traces += 1
                    except Empty:
                        break
                
            except Empty:
                pass
            
            # Flush batch if it has data
            if tenant_batches:
                with self._semaphore:
                    try:
                        # Convert defaultdict to regular dict for serialization
                        batches_to_send = dict(tenant_batches)
                        loop.run_until_complete(self._sender.send_traces_async(batches_to_send))
                    except Exception as e:
                        print(f"[AzureServiceBusTraceExporter] Send error: {e}")
                    finally:
                        tenant_batches.clear()
                        total_traces = 0
        
        # Flush remaining traces on shutdown
        if tenant_batches:
            with self._semaphore:
                try:
                    batches_to_send = dict(tenant_batches)
                    loop.run_until_complete(self._sender.send_traces_async(batches_to_send))
                except Exception as e:
                    print(f"[AzureServiceBusTraceExporter] Send error on shutdown: {e}")
        
        loop.run_until_complete(self._sender.close())
        loop.close()
    
    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush all pending spans."""
        import time
        deadline = time.time() + (timeout_millis / 1000.0)
        
        while not self._queue.empty() and time.time() < deadline:
            time.sleep(0.1)
        
        return True
    
    def shutdown(self):
        """Shutdown the exporter and flush remaining spans."""
        self._stop_event.set()
        self._worker_thread.join(timeout=self._flush_interval + 2)