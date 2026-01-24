#!/usr/bin/env python3
"""CLI for user management (create, list, delete).

Uses service role key for admin operations.
"""

import argparse
import sys

from selko.config import add_logging_arguments, load_config
from selko.logging import setup_logging
from selko.services.users import (
    UserManagementError,
    create_user,
    delete_user,
    list_users,
)


def cmd_create(args, config):
    """Create a new user."""
    try:
        user = create_user(
            config,
            email=args.email,
            password=args.password,
            display_name=args.name,
        )
        print(f"Created user: {user['id']} ({user['email']})")
    except UserManagementError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_list(args, config):
    """List all users."""
    try:
        users = list_users(config)
        if not users:
            print("No users found.")
            return

        print(f"{'ID':<40} EMAIL")
        print("-" * 70)
        for user in users:
            print(f"{user['id']:<40} {user['email']}")
    except UserManagementError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_delete(args, config):
    """Delete a user."""
    try:
        delete_user(config, args.user_id)
        print(f"Deleted user: {args.user_id}")
    except UserManagementError as e:
        print(f"Error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Manage Supabase users",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a user
  uv run python -m cli.cli_user create --email test@example.com --password secret123

  # List all users
  uv run python -m cli.cli_user list

  # Delete a user
  uv run python -m cli.cli_user delete --user-id <uuid>

  # Use staging environment
  ENVIRONMENT=staging uv run python -m cli.cli_user list

  # Enable verbose logging
  uv run python -m cli.cli_user -v list
        """,
    )
    add_logging_arguments(parser)

    subparsers = parser.add_subparsers(dest="command", required=True)

    # create command
    create_parser = subparsers.add_parser("create", help="Create a new user")
    create_parser.add_argument(
        "--email", required=True, help="User email address"
    )
    create_parser.add_argument(
        "--password", required=True, help="User password"
    )
    create_parser.add_argument(
        "--name", help="Display name (defaults to email prefix)"
    )

    # list command
    subparsers.add_parser("list", help="List all users")

    # delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a user")
    delete_parser.add_argument(
        "--user-id", required=True, help="User UUID to delete"
    )

    args = parser.parse_args()
    setup_logging(verbose=args.verbose, quiet=args.quiet)
    config = load_config()

    if args.command == "create":
        cmd_create(args, config)
    elif args.command == "list":
        cmd_list(args, config)
    elif args.command == "delete":
        cmd_delete(args, config)


if __name__ == "__main__":
    main()
