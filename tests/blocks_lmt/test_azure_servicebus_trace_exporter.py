import pytest
import json
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime, timezone
from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExportResult
from opentelemetry.trace import SpanKind, StatusCode
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace.span import TraceState

from blocks_lmt.azure_servicebus_trace_exporter import (
    TraceData,
    FailedTraceBatch,
    LmtServiceBusTraceSender,
    AzureServiceBusTraceExporter
)


class TestTraceData:
    """Test cases for TraceData dataclass."""
    
    def test_trace_data_creation(self):
        """Test creating TraceData instance."""
        trace_data = TraceData(
            Timestamp="2024-01-01T00:00:00Z",
            TraceId="test-trace-id",
            SpanId="test-span-id",
            ParentSpanId="",
            ParentId="",
            Kind="INTERNAL",
            ActivitySourceName="test-source",
            OperationName="test-operation",
            StartTime="2024-01-01T00:00:00Z",
            EndTime="2024-01-01T00:00:01Z",
            Duration=1.0,
            Attributes={},
            Status="OK",
            StatusDescription="",
            Baggage={},
            ServiceName="test-service",
            TenantId="test-tenant"
        )
        
        assert trace_data.TraceId == "test-trace-id"
        assert trace_data.SpanId == "test-span-id"
        assert trace_data.ServiceName == "test-service"
        assert trace_data.TenantId == "test-tenant"
        assert trace_data.Duration == 1.0


class TestLmtServiceBusTraceSender:
    """Test cases for LmtServiceBusTraceSender."""
    
    def test_get_topic_name(self):
        """Test topic name generation."""
        topic_name = LmtServiceBusTraceSender._get_topic_name("test-service")
        assert topic_name == "lmt-test-service"
    
    @pytest.mark.asyncio
    @patch('blocks_lmt.azure_servicebus_trace_exporter.ServiceBusClient')
    async def test_send_traces_async_success(self, mock_client_class, sample_connection_string):
        """Test successful trace sending to Azure Service Bus."""
        mock_sender = AsyncMock()
        mock_client_instance = MagicMock()
        mock_client_instance.get_topic_sender.return_value = mock_sender
        mock_client_class.from_connection_string.return_value = mock_client_instance
        
        sender = LmtServiceBusTraceSender(
            service_name="test-service",
            connection_string=sample_connection_string,
            max_retries=3,
            max_failed_batches=100
        )
        
        trace_data = TraceData(
            Timestamp=datetime.now(timezone.utc).isoformat(),
            TraceId="test-trace-id",
            SpanId="test-span-id",
            ParentSpanId="",
            ParentId="",
            Kind="INTERNAL",
            ActivitySourceName="test-source",
            OperationName="test-operation",
            StartTime=datetime.now(timezone.utc).isoformat(),
            EndTime=datetime.now(timezone.utc).isoformat(),
            Duration=1.0,
            Attributes={},
            Status="OK",
            StatusDescription="",
            Baggage={},
            ServiceName="test-service",
            TenantId="test-tenant"
        )
        
        tenant_batches = {"test-tenant": [trace_data]}
        await sender.send_traces_async(tenant_batches)
        
        # Verify sender was created
        mock_client_class.from_connection_string.assert_called_once()
        mock_client_instance.get_topic_sender.assert_called_once_with("lmt-test-service")
        
        # Verify message was sent
        mock_sender.send_messages.assert_called_once()
        call_args = mock_sender.send_messages.call_args[0][0]
        assert call_args.content_type == "application/json"
        assert "blocks-lmt-service-traces" in call_args.correlation_id
        
        # Verify payload structure
        body_content = b''.join(call_args.body) if hasattr(call_args.body, '__iter__') and not isinstance(call_args.body, (str, bytes)) else call_args.body
        payload = json.loads(body_content)
        assert payload["Type"] == "traces"
        assert payload["ServiceName"] == "test-service"
        assert "test-tenant" in payload["Data"]
        assert len(payload["Data"]["test-tenant"]) == 1
        assert payload["Data"]["test-tenant"][0]["TraceId"] == "test-trace-id"
        
        # Cleanup
        sender._stop_event.set()
        if sender._retry_timer:
            sender._retry_timer.join(timeout=1)
    
    @pytest.mark.asyncio
    @patch('blocks_lmt.azure_servicebus_trace_exporter.ServiceBusClient')
    async def test_send_traces_async_retries_on_failure(self, mock_client_class, sample_connection_string):
        """Test that send_traces_async retries on failure."""
        mock_sender = AsyncMock()
        mock_sender.send_messages.side_effect = [
            Exception("Network error"),
            Exception("Network error"),
            None  # Success on third try
        ]
        
        mock_client_instance = MagicMock()
        mock_client_instance.get_topic_sender.return_value = mock_sender
        mock_client_class.from_connection_string.return_value = mock_client_instance
        
        sender = LmtServiceBusTraceSender(
            service_name="test-service",
            connection_string=sample_connection_string,
            max_retries=3,
            max_failed_batches=100
        )
        
        trace_data = TraceData(
            Timestamp=datetime.now(timezone.utc).isoformat(),
            TraceId="test-trace-id",
            SpanId="test-span-id",
            ParentSpanId="",
            ParentId="",
            Kind="INTERNAL",
            ActivitySourceName="test-source",
            OperationName="test-operation",
            StartTime=datetime.now(timezone.utc).isoformat(),
            EndTime=datetime.now(timezone.utc).isoformat(),
            Duration=1.0,
            Attributes={},
            Status="OK",
            StatusDescription="",
            Baggage={},
            ServiceName="test-service",
            TenantId="test-tenant"
        )
        
        tenant_batches = {"test-tenant": [trace_data]}
        await sender.send_traces_async(tenant_batches)
        
        # Verify it retried (should be called 3 times)
        assert mock_sender.send_messages.call_count == 3
        
        # Cleanup
        sender._stop_event.set()
        if sender._retry_timer:
            sender._retry_timer.join(timeout=1)
    
    @pytest.mark.asyncio
    @patch('blocks_lmt.azure_servicebus_trace_exporter.ServiceBusClient')
    async def test_send_traces_async_queues_failed_batch(self, mock_client_class, sample_connection_string):
        """Test that failed batches are queued for later retry."""
        mock_sender = AsyncMock()
        mock_sender.send_messages.side_effect = Exception("Permanent failure")
        
        mock_client_instance = MagicMock()
        mock_client_instance.get_topic_sender.return_value = mock_sender
        mock_client_class.from_connection_string.return_value = mock_client_instance
        
        sender = LmtServiceBusTraceSender(
            service_name="test-service",
            connection_string=sample_connection_string,
            max_retries=2,
            max_failed_batches=100
        )
        
        trace_data = TraceData(
            Timestamp=datetime.now(timezone.utc).isoformat(),
            TraceId="test-trace-id",
            SpanId="test-span-id",
            ParentSpanId="",
            ParentId="",
            Kind="INTERNAL",
            ActivitySourceName="test-source",
            OperationName="test-operation",
            StartTime=datetime.now(timezone.utc).isoformat(),
            EndTime=datetime.now(timezone.utc).isoformat(),
            Duration=1.0,
            Attributes={},
            Status="OK",
            StatusDescription="",
            Baggage={},
            ServiceName="test-service",
            TenantId="test-tenant"
        )
        
        tenant_batches = {"test-tenant": [trace_data]}
        await sender.send_traces_async(tenant_batches, retry_count=0)
        
        # Verify failed batch was queued
        assert len(sender._failed_trace_batches) == 1
        failed_batch = sender._failed_trace_batches[0]
        assert failed_batch.RetryCount == 1
        assert "test-tenant" in failed_batch.TenantBatches
        
        # Cleanup
        sender._stop_event.set()
        if sender._retry_timer:
            sender._retry_timer.join(timeout=1)


class TestAzureServiceBusTraceExporter:
    """Test cases for AzureServiceBusTraceExporter."""
    
    def test_exporter_creation(self, sample_x_blocks_key, sample_service_id, sample_connection_string):
        """Test exporter creation."""
        exporter = AzureServiceBusTraceExporter(
            x_blocks_key=sample_x_blocks_key,
            service_name=sample_service_id,
            connection_string=sample_connection_string,
            batch_size=100,
            flush_interval=5.0,
            max_retries=3,
            max_failed_batches=100
        )
        
        assert exporter is not None
        assert hasattr(exporter, '_sender')
        assert exporter._x_blocks_key == sample_x_blocks_key
        assert exporter._service_name == sample_service_id
    
    def test_exporter_export_with_empty_spans(self, sample_x_blocks_key, sample_service_id, sample_connection_string):
        """Test export with empty span list."""
        exporter = AzureServiceBusTraceExporter(
            x_blocks_key=sample_x_blocks_key,
            service_name=sample_service_id,
            connection_string=sample_connection_string
        )
        
        result = exporter.export([])
        assert result == SpanExportResult.SUCCESS
    
    def test_exporter_handles_span_conversion_errors(self, sample_x_blocks_key, sample_service_id, sample_connection_string):
        """Test that exporter handles errors during span conversion."""
        exporter = AzureServiceBusTraceExporter(
            x_blocks_key=sample_x_blocks_key,
            service_name=sample_service_id,
            connection_string=sample_connection_string
        )
        
        # Create a mock span that will cause conversion issues
        mock_span = Mock(spec=ReadableSpan)
        mock_span.get_span_context.side_effect = Exception("Conversion error")
        
        # Should handle the error and return FAILURE
        result = exporter.export([mock_span])
        assert result == SpanExportResult.FAILURE
    
    def test_exporter_shutdown(self, sample_x_blocks_key, sample_service_id, sample_connection_string):
        """Test exporter shutdown."""
        exporter = AzureServiceBusTraceExporter(
            x_blocks_key=sample_x_blocks_key,
            service_name=sample_service_id,
            connection_string=sample_connection_string
        )
        
        exporter.shutdown()
        # Shutdown should complete without error
    
    def test_exporter_force_flush(self, sample_x_blocks_key, sample_service_id, sample_connection_string):
        """Test exporter force flush."""
        exporter = AzureServiceBusTraceExporter(
            x_blocks_key=sample_x_blocks_key,
            service_name=sample_service_id,
            connection_string=sample_connection_string
        )
        
        result = exporter.force_flush()
        assert result is True

