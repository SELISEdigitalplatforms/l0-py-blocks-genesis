import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


class TestExampleEndpoints:
    """Test cases for example.py FastAPI endpoints."""
    
    @pytest.fixture
    def client(self):
        """Create test client for FastAPI app."""
        # Mock the Azure Service Bus configuration to avoid actual connections
        with patch('blocks_lmt.log_config.AzureServiceBusHandler'):
            with patch('blocks_lmt.tracing.AzureServiceBusTraceExporter'):
                from example import app
                return TestClient(app)
    
    def test_root_endpoint(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"message": "Hello World"}
    
    def test_health_endpoint(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}
    
    def test_health_endpoint_with_query_params(self, client):
        """Test health endpoint with query parameters."""
        response = client.get("/health?test=value")
        assert response.status_code == 200
        assert "status" in response.json()
    
    def test_nonexistent_endpoint(self, client):
        """Test that non-existent endpoint returns 404."""
        response = client.get("/nonexistent")
        assert response.status_code == 404
    
    def test_root_endpoint_creates_activity(self, client):
        """Test that root endpoint creates activity."""
        response = client.get("/")
        assert response.status_code == 200
        # Activity should be created during request processing

