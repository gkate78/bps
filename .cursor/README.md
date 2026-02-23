# Cursor Rules for FastAPI MVC Projects

## Overview

This folder contains Cursor AI rules that guide code generation and suggestions for FastAPI MVC projects. The rules file (`fastapi-mvc.mdc`) is automatically applied to all code generation in this workspace.

## What is `fastapi-mvc.mdc`?

The `.mdc` file is a Cursor rules file that defines:
- **Architecture patterns** - MVC structure, file organization
- **FastAPI best practices** - Application setup, routing, dependency injection
- **Frontend guidelines** - TailwindCSS + Vanilla JS patterns, mobile-first design
- **Coding standards** - Python conventions, error handling, type safety
- **Database patterns** - SQLAlchemy/SQLModel setup, CRUD operations
- **Security practices** - Authentication, input validation, XSS/CSRF prevention
- **Deployment** - Fly.io configuration, volume persistence
- **Design system** - Vibecamp branding guidelines

## How It Works

- **Automatic Application**: The `alwaysApply: true` setting means these rules are always active
- **Code Generation**: When you ask Cursor to generate code, it follows these patterns
- **Suggestions**: Code suggestions and completions align with these guidelines
- **Consistency**: Ensures all code follows the same architectural and style patterns

## Key Sections

1. **Architecture** - Project structure and MVC organization
2. **FastAPI** - Application setup and routing patterns
3. **Frontend** - TailwindCSS templates and mobile-first design
4. **Database** - SQLAlchemy/SQLModel async patterns
5. **Security** - Comprehensive security best practices
6. **Deployment** - Fly.io volume configuration and backups
7. **Design System** - Vibecamp branding and component patterns

## Usage

No action needed - the rules are automatically applied. When working on FastAPI projects, Cursor will:
- Suggest code following MVC architecture
- Use async patterns for database operations
- Apply mobile-first TailwindCSS patterns
- Follow security best practices
- Use Vibecamp design system components

## Modifying Rules

Edit `fastapi-mvc.mdc` to:
- Add new patterns or guidelines
- Update existing best practices
- Adjust project structure requirements
- Modify design system components

Changes take effect immediately for new code generation.
