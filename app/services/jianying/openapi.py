def get_openapi_spec():
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "VideoFactory MCP API",
            "version": "1.0.0",
            "description": "Unified MCP service API for JianYing operations",
        },
        "paths": {
            "/api/mcp/execute": {
                "post": {
                    "summary": "Execute MCP action",
                    "parameters": [
                        {"name": "X-API-Key", "in": "header", "required": False, "schema": {"type": "string"}},
                        {"name": "X-User-Id", "in": "header", "required": False, "schema": {"type": "string"}}
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "action": {"type": "string"},
                                        "params": {"type": "object"},
                                    },
                                    "required": ["action"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {"description": "OK"},
                        "400": {"description": "Invalid action"},
                        "401": {"description": "Unauthorized"},
                        "429": {"description": "Rate limited"},
                    },
                }
            },
            "/api/mcp/batch/enqueue": {
                "post": {
                    "summary": "Enqueue batch generation job",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"type": "object"}
                            }
                        },
                    },
                    "responses": {
                        "200": {"description": "OK"},
                        "400": {"description": "Bad request"},
                    },
                }
            },
            "/api/mcp/openapi": {
                "get": {
                    "summary": "Get OpenAPI spec",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/mcp/docs": {
                "get": {
                    "summary": "Swagger UI",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/mcp/admin/keys": {
                "get": {
                    "summary": "List API keys (admin)",
                    "responses": {"200": {"description": "OK"}},
                },
                "post": {
                    "summary": "Create API key (admin)",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/mcp/admin/keys/{id}/revoke": {
                "post": {
                    "summary": "Revoke API key (admin)",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
                    ],
                    "responses": {"200": {"description": "OK"}, "404": {"description": "Not Found"}},
                }
            },
            "/api/mcp/admin/keys/{id}/delete": {
                "post": {
                    "summary": "Delete API key (admin)",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
                    ],
                    "responses": {"200": {"description": "OK"}, "404": {"description": "Not Found"}},
                }
            },
            "/api/mcp/admin/keys/{id}/update": {
                "post": {
                    "summary": "Update API key (admin)",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
                    ],
                    "responses": {"200": {"description": "OK"}, "404": {"description": "Not Found"}},
                }
            },
            "/api/mcp/admin/usage": {
                "get": {
                    "summary": "Usage list (admin)",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/mcp/admin/audit": {
                "get": {
                    "summary": "Audit logs (admin)",
                    "parameters": [
                        {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                        {"name": "offset", "in": "query", "schema": {"type": "integer"}},
                        {"name": "action", "in": "query", "schema": {"type": "string"}},
                        {"name": "status", "in": "query", "schema": {"type": "string"}},
                        {"name": "client_id", "in": "query", "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/mcp/admin/audit/export": {
                "get": {
                    "summary": "Export audit logs (admin)",
                    "parameters": [
                        {"name": "format", "in": "query", "schema": {"type": "string"}},
                        {"name": "fields", "in": "query", "schema": {"type": "string"}},
                        {"name": "action", "in": "query", "schema": {"type": "string"}},
                        {"name": "status", "in": "query", "schema": {"type": "string"}},
                        {"name": "client_id", "in": "query", "schema": {"type": "string"}}
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/mcp/admin/quotas": {
                "get": {
                    "summary": "List quotas (admin)",
                    "responses": {"200": {"description": "OK"}},
                },
                "post": {
                    "summary": "Upsert quota (admin)",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/mcp/admin/quotas/group": {
                "post": {
                    "summary": "Upsert quotas by group (admin)",
                    "responses": {"200": {"description": "OK"}, "404": {"description": "Not Found"}},
                }
            },
            "/api/mcp/admin/quotas/template": {
                "post": {
                    "summary": "Apply quota template by group (admin)",
                    "responses": {"200": {"description": "OK"}, "404": {"description": "Not Found"}},
                }
            },
            "/api/mcp/admin/templates": {
                "get": {
                    "summary": "List quota templates (admin)",
                    "responses": {"200": {"description": "OK"}},
                },
                "post": {
                    "summary": "Upsert quota template (admin)",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/mcp/admin/templates/{id}/delete": {
                "post": {
                    "summary": "Delete quota template (admin)",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
                    ],
                    "responses": {"200": {"description": "OK"}, "404": {"description": "Not Found"}},
                }
            },
            "/api/mcp/admin/permissions/template": {
                "post": {
                    "summary": "Apply permission template to key (admin)",
                    "responses": {"200": {"description": "OK"}, "400": {"description": "Bad Request"}},
                }
            },
            "/api/mcp/admin/quotas/{id}/delete": {
                "post": {
                    "summary": "Delete quota (admin)",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
                    ],
                    "responses": {"200": {"description": "OK"}, "404": {"description": "Not Found"}},
                }
            },
            "/admin/mcp/": {
                "get": {
                    "summary": "MCP Admin Console",
                    "responses": {"200": {"description": "OK"}},
                }
            },
        },
    }
