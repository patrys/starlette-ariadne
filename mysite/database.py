import asyncio

from gino import Gino

db = Gino()


class Note(db.Model):
    __tablename__ = "notes"

    id = db.Column(db.Integer(), primary_key=True)
    title = db.Column(db.String())
    body = db.Column(db.Text())
