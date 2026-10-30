"""Shared extension objects, created once and bound to the app in create_app()."""
import sqlite3

from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
socketio = SocketIO()


@event.listens_for(Engine, "connect")
def _configure_sqlite(dbapi_connection, _connection_record):
    """Turn on foreign-key checks and WAL mode for every SQLite connection.

    SQLite ignores foreign keys unless asked, and WAL (write-ahead logging)
    lets readers continue while another thread is writing.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
