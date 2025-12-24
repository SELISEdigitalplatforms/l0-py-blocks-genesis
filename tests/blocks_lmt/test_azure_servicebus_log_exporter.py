import pytest
import logging
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime, timezone

from blocks_lmt.azure_servicebus_log_exporter import (
    LogData,
    FailedLogBatch,
    LmtServiceBusSender,
    TraceContextFilter,
    AzureServiceBusHandler,
    AzureServiceBusLogBatcher
)


class TestLogData:
    """Test cases for LogData dataclass."""
    
    def test_log_data_creation(self):
        """Test creating LogData instance."""
        log_data = LogData(
            Timestamp="2024-01-01T00:00:00Z",
            Level="INFO",
            Message="Test message",
            Exception="",
            ServiceName="test-service",
            Properties={},
            TenantId="test-tenant"
        )
        
        assert log_data.Level == "INFO"
        assert log_data.Message == "Test message"
        assert log_data.ServiceName == "test-service"


class TestLmtServiceBusSender:
    """Test cases for LmtServiceBusSender."""
    
    def test_get_topic_name(self):
        """Test topic name generation."""
        topic_name = LmtServiceBusSender._get_topic_name("test-service")
        assert topic_name == "lmt-test-service"
    
    @pytest.mark.asyncio
    @patch('blocks_lmt.azure_servicebus_log_exporter.ServiceBusClient')
    async def test_send_logs_async_success(self, mock_client_class, sample_connection_string):
        """Test successful log sending to Azure Service Bus."""
        mock_sender = AsyncMock()
        mock_client_instance = MagicMock()
        mock_client_instance.get_topic_sender.return_value = mock_sender
        mock_client_class.from_connection_string.return_value = mock_client_instance
        
        sender = LmtServiceBusSender(
            service_name="test-service",
            connection_string=sample_connection_string,
            max_retries=3,
            max_failed_batches=100
        )
        
        log_data = LogData(
            Timestamp=datetime.now(timezone.utc).isoformat(),
            Level="INFO",
            Message="Test log",
            Exception="",
            ServiceName="test-service",
            Properties={},
            TenantId="test-tenant"
        )
        
        await sender.send_logs_async([log_data])
        
        # Verify sender was created
        mock_client_class.from_connection_string.assert_called_once()
        mock_client_instance.get_topic_sender.assert_called_once_with("lmt-test-service")
        
        # Verify message was sent
        mock_sender.send_messages.assert_called_once()
        call_args = mock_sender.send_messages.call_args[0][0]
        assert call_args.content_type == "application/json"
        assert "blocks-lmt-service-logs" in call_args.correlation_id
        
        # Verify payload structure
        import json
        # call_args.body is a generator, so we need to get the actual body
        body_content = b''.join(call_args.body) if hasattr(call_args.body, '__iter__') and not isinstance(call_args.body, (str, bytes)) else call_args.body
        payload = json.loads(body_content)
        assert payload["Type"] == "logs"
        assert payload["ServiceName"] == "test-service"
        assert len(payload["Data"]) == 1
        assert payload["Data"][0]["Level"] == "INFO"
        
        # Cleanup
        sender._stop_event.set()
        if sender._retry_timer:
            sender._retry_timer.join(timeout=1)
    
    @pytest.mark.asyncio
    @patch('blocks_lmt.azure_servicebus_log_exporter.ServiceBusClient')
    async def test_send_logs_async_retries_on_failure(self, mock_client_class, sample_connection_string):
        """Test that send_logs_async retries on failure."""
        mock_sender = AsyncMock()
        mock_sender.send_messages.side_effect = [
            Exception("Network error"),
            Exception("Network error"),
            None  # Success on third try
        ]
        
        mock_client_instance = MagicMock()
        mock_client_instance.get_topic_sender.return_value = mock_sender
        mock_client_class.from_connection_string.return_value = mock_client_instance
        
        sender = LmtServiceBusSender(
            service_name="test-service",
            connection_string=sample_connection_string,
            max_retries=3,
            max_failed_batches=100
        )
        
        log_data = LogData(
            Timestamp=datetime.now(timezone.utc).isoformat(),
            Level="INFO",
            Message="Test log",
            Exception="",
            ServiceName="test-service",
            Properties={},
            TenantId="test-tenant"
        )
        
        await sender.send_logs_async([log_data])
        
        # Verify it retried (should be called 3 times)
        assert mock_sender.send_messages.call_count == 3
        
        # Cleanup
        sender._stop_event.set()
        if sender._retry_timer:
            sender._retry_timer.join(timeout=1)
    
    @pytest.mark.asyncio
    @patch('blocks_lmt.azure_servicebus_log_exporter.ServiceBusClient')
    async def test_send_logs_async_queues_failed_batch(self, mock_client_class, sample_connection_string):
        """Test that failed batches are queued for later retry."""
        mock_sender = AsyncMock()
        mock_sender.send_messages.side_effect = Exception("Permanent failure")
        
        mock_client_instance = MagicMock()
        mock_client_instance.get_topic_sender.return_value = mock_sender
        mock_client_class.from_connection_string.return_value = mock_client_instance
        
        sender = LmtServiceBusSender(
            service_name="test-service",
            connection_string=sample_connection_string,
            max_retries=2,
            max_failed_batches=100
        )
        
        log_data = LogData(
            Timestamp=datetime.now(timezone.utc).isoformat(),
            Level="INFO",
            Message="Test log",
            Exception="",
            ServiceName="test-service",
            Properties={},
            TenantId="test-tenant"
        )
        
        await sender.send_logs_async([log_data], retry_count=0)
        
        # Verify failed batch was queued
        assert len(sender._failed_log_batches) == 1
        failed_batch = sender._failed_log_batches[0]
        assert failed_batch.RetryCount == 1
        assert len(failed_batch.Logs) == 1
        
        # Cleanup
        sender._stop_event.set()
        if sender._retry_timer:
            sender._retry_timer.join(timeout=1)


class TestTraceContextFilter:
    """Test cases for TraceContextFilter."""
    
    def test_filter_adds_tenant_id(self):
        """Test that filter adds tenant ID."""
        filter_obj = TraceContextFilter(x_blocks_key="test-tenant")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        result = filter_obj.filter(record)
        assert result is True
        assert hasattr(record, 'TenantId')
        assert record.TenantId == "test-tenant"
    
    def test_filter_adds_trace_context(self):
        """Test that filter adds trace context."""
        filter_obj = TraceContextFilter(x_blocks_key="test-tenant")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        filter_obj.filter(record)
        assert hasattr(record, 'TraceId')
        assert hasattr(record, 'SpanId')
    
    def test_filter_without_tenant_id(self):
        """Test filter with empty tenant ID."""
        filter_obj = TraceContextFilter(x_blocks_key="")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        filter_obj.filter(record)
        assert hasattr(record, 'TenantId')
        assert record.TenantId == "miscellaneous"


class TestAzureServiceBusHandler:
    """Test cases for AzureServiceBusHandler."""
    
    def test_handler_creation(self, sample_x_blocks_key, sample_service_id, sample_connection_string):
        """Test handler creation."""
        handler = AzureServiceBusHandler(
            x_blocks_key=sample_x_blocks_key,
            service_name=sample_service_id,
            connection_string=sample_connection_string,
            batch_size=10,
            flush_interval_sec=1.0,
            max_retries=1,
            max_failed_batches=10
        )
        
        assert handler is not None
        assert hasattr(handler, 'log_batcher')
    
    def test_handler_emit(self, sample_x_blocks_key, sample_service_id, sample_connection_string):
        """Test handler emit method."""
        handler = AzureServiceBusHandler(
            x_blocks_key=sample_x_blocks_key,
            service_name=sample_service_id,
            connection_string=sample_connection_string,
            batch_size=10,
            flush_interval_sec=1.0,
            max_retries=1,
            max_failed_batches=10
        )
        
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        handler.emit(record)


class TestAzureServiceBusLogBatcher:
    """Test cases for AzureServiceBusLogBatcher."""
    
    def test_enqueue_converts_log_record_to_log_data(self, sample_x_blocks_key, sample_service_id, sample_connection_string):
        """Test that enqueue converts LogRecord to LogData and adds to queue."""
        batcher = AzureServiceBusLogBatcher(
            x_blocks_key=sample_x_blocks_key,
            service_name=sample_service_id,
            connection_string=sample_connection_string,
            batch_size=10,
            flush_interval_sec=1.0,
            max_retries=1,
            max_failed_batches=10
        )
        
        # Create a log record with trace context
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test log message",
            args=(),
            exc_info=None
        )
        record.TenantId = "test-tenant"
        record.TraceId = "abc123traceid"
        record.SpanId = "def456spanid"
        
        # Enqueue the record
        batcher.enqueue(record)
        
        # Verify queue has one item
        assert batcher.queue.qsize() == 1
        
        # Get the LogData from queue
        log_data = batcher.queue.get()
        
        # Verify conversion
        assert log_data.Level == "INFO"
        assert log_data.Message == "Test log message"
        assert log_data.ServiceName == sample_service_id
        assert log_data.TenantId == "test-tenant"
        assert log_data.Properties["LoggerName"] == "test_logger"
        assert log_data.Properties["TraceId"] == "abc123traceid"
        assert log_data.Properties["SpanId"] == "def456spanid"
        
        # Cleanup
        batcher.stop()
    
    @patch('blocks_lmt.azure_servicebus_log_exporter.Activity')
    def test_enqueue_uses_activity_trace_context_when_missing(self, mock_activity, sample_x_blocks_key, sample_service_id, sample_connection_string):
        """Test that enqueue uses Activity trace context when not in record."""
        mock_activity.get_trace_id.return_value = "activity_trace_id"
        mock_activity.get_span_id.return_value = "activity_span_id"
        
        batcher = AzureServiceBusLogBatcher(
            x_blocks_key=sample_x_blocks_key,
            service_name=sample_service_id,
            connection_string=sample_connection_string,
            batch_size=10,
            flush_interval_sec=1.0,
            max_retries=1,
            max_failed_batches=10
        )
        
        # Create log record without trace context
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        # Enqueue without trace context in record
        batcher.enqueue(record)
        
        log_data = batcher.queue.get()
        
        # Verify trace context was added from Activity
        assert log_data.Properties["TraceId"] == "activity_trace_id"
        assert log_data.Properties["SpanId"] == "activity_span_id"
        
        # Cleanup
        batcher.stop()
    
    def test_enqueue_handles_exception_info(self, sample_x_blocks_key, sample_service_id, sample_connection_string):
        """Test that enqueue properly handles exception information."""
        batcher = AzureServiceBusLogBatcher(
            x_blocks_key=sample_x_blocks_key,
            service_name=sample_service_id,
            connection_string=sample_connection_string,
            batch_size=10,
            flush_interval_sec=1.0,
            max_retries=1,
            max_failed_batches=10
        )
        
        try:
            raise ValueError("Test exception")
        except ValueError as e:
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="test.py",
                lineno=1,
                msg="Error occurred",
                args=(),
                exc_info=(type(e), e, e.__traceback__)
            )
            
            batcher.enqueue(record)
            log_data = batcher.queue.get()
            
            assert log_data.Level == "ERROR"
            assert "ValueError" in log_data.Exception or "Test exception" in log_data.Exception
            
        # Cleanup
        batcher.stop()
    
    def test_enqueue_uses_default_tenant_id(self, sample_x_blocks_key, sample_service_id, sample_connection_string):
        """Test that enqueue uses default tenant ID when not in record."""
        batcher = AzureServiceBusLogBatcher(
            x_blocks_key=sample_x_blocks_key,
            service_name=sample_service_id,
            connection_string=sample_connection_string,
            batch_size=10,
            flush_interval_sec=1.0,
            max_retries=1,
            max_failed_batches=10
        )
        
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None
        )
        # Don't set TenantId on record
        
        batcher.enqueue(record)
        log_data = batcher.queue.get()
        
        # Verify default tenant ID was used
        assert log_data.TenantId == sample_x_blocks_key
        
        # Cleanup
        batcher.stop()

