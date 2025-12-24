import pytest
from unittest.mock import Mock, MagicMock, patch
from opentelemetry.trace import StatusCode
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter

from blocks_lmt.activity import Activity


class TestActivity:
    """Test cases for Activity class."""
    
    def test_activity_start(self):
        """Test creating a new activity."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        with Activity.start("test_activity") as activity:
            assert activity is not None
            assert hasattr(activity, '_span')
            assert hasattr(activity, '_context')
    
    def test_activity_set_property(self):
        """Test setting a single property on activity."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        with Activity.start("test_activity") as activity:
            activity.set_property("test_key", "test_value")
            activity.set_property("numeric_key", 123)
            assert activity is not None
    
    def test_activity_set_properties(self):
        """Test setting multiple properties."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        with Activity.start("test_activity") as activity:
            props = {
                "key1": "value1",
                "key2": "value2",
                "key3": 123
            }
            activity.set_properties(props)
            assert activity is not None
    
    def test_activity_set_status(self):
        """Test setting status on activity."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        with Activity.start("test_activity") as activity:
            activity.set_status(StatusCode.OK, "Success")
            activity.set_status(StatusCode.ERROR, "Error occurred")
            assert activity is not None
    
    def test_activity_context_manager(self):
        """Test activity as context manager."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        with Activity.start("test_activity") as activity:
            assert activity is not None
    
    def test_activity_exception_handling(self):
        """Test activity handles exceptions correctly."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        with pytest.raises(ValueError):
            with Activity.start("test_activity") as activity:
                raise ValueError("Test error")
    
    def test_activity_stop(self):
        """Test manually stopping activity."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        activity = Activity.start("test_activity")
        assert activity is not None
        activity.stop()
    
    def test_get_trace_id(self):
        """Test getting trace ID."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        with Activity.start("test_activity"):
            trace_id = Activity.get_trace_id()
            assert isinstance(trace_id, str)
            assert len(trace_id) == 32 or trace_id == ""
    
    def test_get_span_id(self):
        """Test getting span ID."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        with Activity.start("test_activity"):
            span_id = Activity.get_span_id()
            assert isinstance(span_id, str)
            assert len(span_id) == 16 or span_id == ""
    
    def test_get_trace_id_no_span(self):
        """Test getting trace ID when no span is active."""
        trace_id = Activity.get_trace_id()
        # When no span is active, returns empty string or zero-filled string
        assert trace_id == "" or trace_id == "00000000000000000000000000000000"
    
    def test_get_span_id_no_span(self):
        """Test getting span ID when no span is active."""
        span_id = Activity.get_span_id()
        # When no span is active, returns empty string or zero-filled string
        assert span_id == "" or span_id == "0000000000000000"
    
    def test_set_current_property(self):
        """Test setting property on current span."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        with Activity.start("test_activity"):
            Activity.set_current_property("test_key", "test_value")
    
    def test_set_current_properties(self):
        """Test setting multiple properties on current span."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        with Activity.start("test_activity"):
            Activity.set_current_properties({
                "key1": "value1",
                "key2": "value2"
            })
    
    def test_set_current_properties_no_span(self):
        """Test setting properties when no span is active."""
        Activity.set_current_properties({"key": "value"})
    
    def test_set_current_status(self):
        """Test setting status on current span."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        with Activity.start("test_activity"):
            Activity.set_current_status(StatusCode.OK, "Success")
    
    def test_set_current_status_no_span(self):
        """Test setting status when no span is active."""
        Activity.set_current_status(StatusCode.OK, "Success")
    
    def test_activity_current(self):
        """Test getting current span."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        span = Activity.current()
        
        with Activity.start("test_activity"):
            span = Activity.current()
    
    def test_get_root_attribute(self):
        """Test getting root attribute."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        with Activity.start("test_activity") as activity:
            result = activity.get_root_attribute("nonexistent")
            assert result is None
    
    def test_get_all_root_attributes(self):
        """Test getting all root attributes."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        with Activity.start("test_activity") as activity:
            attrs = activity.get_all_root_attributes()
            assert isinstance(attrs, dict)
    
    def test_nested_activities(self):
        """Test nested activity creation."""
        provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        
        with Activity.start("parent_activity") as parent:
            with Activity.start("child_activity") as child:
                assert parent is not None
                assert child is not None
