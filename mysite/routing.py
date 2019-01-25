import asyncio

from ariadne import gql, ResolverMap
from ariadne.executable_schema import make_executable_schema
from graphql.pyutils import EventEmitter, EventEmitterAsyncIterator
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware

from .database import Note, db
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
    notes: [Note!]!
}

type Mutation {
    createNote(title: String!, body: String!): Note!
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


@query.field("notes")
async def get_all_notes(root, info):
    notes = await Note.query.gino.all()
    return notes


@mutation.field("createNote")
async def create_note(root, info, title: str, body: str):
    note = await Note.create(title=title, body=body)
    return note


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


async def init_database():
    await db.set_bind("postgresql://localhost/gino")
    await db.gino.create_all()


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
app.add_event_handler("startup", init_database)
app.debug = True
