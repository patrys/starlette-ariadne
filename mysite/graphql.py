import asyncio
import json
from functools import partial
from typing import Any, AsyncGenerator, cast

from ariadne.constants import (
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_TEXT_HTML,
    CONTENT_TYPE_TEXT_PLAIN,
    DATA_TYPE_JSON,
    PLAYGROUND_HTML,
)
from ariadne.exceptions import HttpBadRequestError, HttpError, HttpMethodNotAllowedError
from ariadne.types import Bindable
from graphql import (
    ExecutionResult,
    GraphQLError,
    GraphQLSchema,
    format_error,
    graphql,
    parse,
    subscribe,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.websockets import WebSocket


GQL_CONNECTION_INIT = "connection_init"  # Client -> Server
GQL_CONNECTION_ACK = "connection_ack"  # Server -> Client
GQL_CONNECTION_ERROR = "connection_error"  # Server -> Client

# NOTE: The keep alive message type does not follow the standard due to connection optimizations
GQL_CONNECTION_KEEP_ALIVE = "ka"  # Server -> Client

GQL_CONNECTION_TERMINATE = "connection_terminate"  # Client -> Server
GQL_START = "start"  # Client -> Server
GQL_DATA = "data"  # Server -> Client
GQL_ERROR = "error"  # Server -> Client
GQL_COMPLETE = "complete"  # Server -> Client
GQL_STOP = "stop"  # Client -> Server


async def extract_data_from_request(request: Request) -> dict:
    if request.headers.get("Content-Type") != DATA_TYPE_JSON:
        raise HttpBadRequestError(
            "Posted content must be of type {}".format(DATA_TYPE_JSON)
        )

    data = await request.json()
    if not isinstance(data, dict):
        raise GraphQLError("Valid request body should be a JSON object")

    query = data.get("query")
    variables = data.get("variables")
    operation_name = data.get("operationName")

    return query, variables, operation_name


async def graphql_playground(request: Request) -> HTMLResponse:
    response = HTMLResponse(PLAYGROUND_HTML)
    return response


def default_context_for_request(request: Any) -> Any:
    return {"request": request}


async def graphql_http_server(
    request: Request,
    *,
    schema: GraphQLSchema,
    prepare_context=default_context_for_request
) -> Response:
    try:
        query, variables, operation_name = await extract_data_from_request(request)
        result = await graphql(
            schema,
            query,
            root_value=None,
            context_value=prepare_context(request),
            variable_values=variables,
            operation_name=operation_name,
        )
    except GraphQLError as error:
        response = {"errors": [{"message": error.message}]}
        return JSONResponse(response)
    except HttpError as error:
        response = error.message or error.status
        return Response(response, status_code=400)
    else:
        response = {"data": result.data}
        if result.errors:
            response["errors"] = [format_error(e) for e in result.errors]
        return JSONResponse(response)


async def extract_data_from_websocket(message: dict) -> None:
    payload = cast(dict, message.get("payload"))
    if not isinstance(payload, dict):
        raise GraphQLError("Payload must be an object")

    query = payload.get("query")
    variables = payload.get("variables")
    operation_name = payload.get("operationName")

    return query, variables, operation_name


async def observe_async_results(
    results: AsyncGenerator, operation_id: str, websocket: WebSocket
):
    async for result in results:
        payload = {}
        if result.data:
            payload["data"] = result.data
        if result.errors:
            payload["errors"] = [format_error(e) for e in result.errors]
        await send_json(
            websocket, {"type": GQL_DATA, "id": operation_id, "payload": payload}
        )
    await send_json(websocket, {"type": GQL_COMPLETE, "id": operation_id})


async def receive_json(websocket: WebSocket):
    message = await websocket.receive_text()
    return json.loads(message)


async def send_json(websocket, message):
    message = json.dumps(message)
    await websocket.send_text(message)


async def graphql_ws_server(
    websocket: WebSocket,
    *,
    schema: GraphQLSchema,
    prepare_context=default_context_for_request
):
    subscriptions = {}
    await websocket.accept("graphql-ws")
    while True:
        message = await receive_json(websocket)
        operation_id = cast(str, message.get("id"))
        message_type = cast(str, message.get("type"))

        if message_type == GQL_CONNECTION_INIT:
            await send_json(websocket, {"type": GQL_CONNECTION_ACK})
        elif message_type == GQL_CONNECTION_TERMINATE:
            break
        elif message_type == GQL_START:
            query, variables, operation_name = await extract_data_from_websocket(
                message
            )
            results = await subscribe(
                schema,
                parse(query),
                root_value=None,
                context_value=prepare_context(message),
                variable_values=variables,
                operation_name=operation_name,
            )
            if isinstance(results, ExecutionResult):
                payload = {"message": format_error(results.errors[0])}
                await send_json(
                    websocket,
                    {"type": GQL_ERROR, "id": operation_id, "payload": payload},
                )
            else:
                subscriptions[operation_id] = results
                asyncio.ensure_future(
                    observe_async_results(results, operation_id, websocket)
                )
        elif message_type == GQL_STOP:
            if operation_id in subscriptions:
                await subscriptions[operation_id].aclose()
                del subscriptions[operation_id]


def app_for_schema(schema: GraphQLSchema, *, debug: bool = False):
    async def graphql_http_server_for_schema(request: Request) -> Response:
        return await graphql_http_server(request, schema=schema)

    async def graphql_ws_server_for_schema(websocket: WebSocket) -> None:
        return await graphql_ws_server(websocket, schema=schema)

    app = Starlette(debug=debug)
    app.add_route("/", graphql_playground, methods=["GET"])
    app.add_route("/", graphql_http_server_for_schema, methods=["POST"])
    app.add_websocket_route("/", graphql_ws_server_for_schema)
    return app
