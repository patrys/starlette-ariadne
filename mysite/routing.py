import asyncio

from ariadne import gql, ResolverMap
from ariadne.executable_schema import make_executable_schema
from graphql.pyutils import EventEmitter, EventEmitterAsyncIterator
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware

from .graphql import GraphQL
from .subscription import SubscriptionAwareResolverMap


SCHEMA = gql(
    """
type Note {
    id: ID!
    title: String
    body: String
}

type Query {
    hello: String!
}

type Mutation {
    sendMessage(message: String!): Boolean!
}

type Subscription {
    messages: String!
}
"""
)
mutation = ResolverMap("Mutation")
pubsub = EventEmitter()
query = ResolverMap("Query")
subscription = SubscriptionAwareResolverMap("Subscription")


@query.field("hello")
async def say_hello(root, info):
    await asyncio.sleep(3)
    return "Hello!"


@mutation.field("sendMessage")
async def send_message(root, info, message):
    pubsub.emit("message", message)
    return True


@subscription.subscription("messages")
def subscribe_messages(root, info):
    return EventEmitterAsyncIterator(pubsub, "message")


@subscription.field("messages")
def push_message(message, info):
    return message


schema = make_executable_schema(SCHEMA, [mutation, query, subscription])

graphql_server = GraphQL(schema)

app = Starlette()
app.add_route("/graphql/", graphql_server)
app.add_websocket_route("/graphql/", graphql_server)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=[
        "accept",
        "accept-language",
        "content-language",
        "content-type",
        "x-apollo-tracing",
    ],
)
app.debug = True
