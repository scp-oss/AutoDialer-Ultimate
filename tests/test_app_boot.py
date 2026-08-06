"""App factory / OpenAPI schema sanity checks (no DB required)."""


def test_create_app_registers_routes(app):
    assert len(app.routes) > 100


def test_openapi_schema_generates_without_duplicate_operation_ids(app):
    schema = app.openapi()
    assert schema["paths"]
    operation_ids = [
        op["operationId"]
        for path in schema["paths"].values()
        for op in path.values()
        if isinstance(op, dict) and "operationId" in op
    ]
    assert len(operation_ids) == len(set(operation_ids)), "duplicate OpenAPI operationId found"


def test_health_router_and_websocket_router_present(app):
    paths = {route.path for route in app.routes}
    assert "/api/health" in paths
    assert "/api/ws/dashboard" in paths
