"""Command-line helpers, run as:  flask --app run <command>"""
import click

from .extensions import db
from .models import ROLES, User


def register_cli(app):
    @app.cli.command("init-db")
    def init_db_command():
        """Create any missing tables. Existing data is never deleted."""
        db.create_all()
        click.echo("Database tables are ready.")

    @app.cli.command("create-user")
    @click.argument("username")
    @click.option("--name", "display_name", required=True, help="Name shown in the app.")
    @click.option("--role", type=click.Choice(list(ROLES)), required=True)
    @click.password_option(help="At least 8 characters (prompted if omitted).")
    def create_user_command(username, display_name, role, password):
        """Add a student or lab assistant account."""
        username = username.strip().lower()
        if User.query.filter_by(username=username).first():
            raise click.ClickException(f"User '{username}' already exists.")
        if len(password) < 8:
            raise click.ClickException("The password must be at least 8 characters.")
        user = User(username=username, display_name=display_name.strip(), role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Created {ROLES[role]} account '{username}'.")
