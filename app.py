"""Example Flask application entry point."""

import os

from flask import Flask, abort, jsonify, request


def create_app() -> Flask:
    """Application factory: builds and configures the Flask app."""
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        JSON_SORT_KEYS=False,
    )

    # In-memory "database" for the demo
    todos = {1: {"id": 1, "title": "Learn Flask", "done": False}}

    @app.get("/")
    def index():
        return jsonify(message="Hello from Flask!")

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/todos")
    def list_todos():
        return jsonify(list(todos.values()))

    @app.get("/todos/<int:todo_id>")
    def get_todo(todo_id: int):
        todo = todos.get(todo_id)
        if todo is None:
            abort(404, description="Todo not found")
        return jsonify(todo)

    @app.post("/todos")
    def create_todo():
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip()
        if not title:
            abort(400, description="'title' is required")
        new_id = max(todos, default=0) + 1
        todos[new_id] = {"id": new_id, "title": title, "done": False}
        return jsonify(todos[new_id]), 201

    @app.patch("/todos/<int:todo_id>")
    def update_todo(todo_id: int):
        todo = todos.get(todo_id)
        if todo is None:
            abort(404, description="Todo not found")
        data = request.get_json(silent=True) or {}
        if "title" in data:
            todo["title"] = str(data["title"]).strip()
        if "done" in data:
            todo["done"] = bool(data["done"])
        return jsonify(todo)

    @app.delete("/todos/<int:todo_id>")
    def delete_todo(todo_id: int):
        if todos.pop(todo_id, None) is None:
            abort(404, description="Todo not found")
        return "", 204

    # Return JSON instead of HTML for errors
    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(405)
    def handle_error(err):
        return jsonify(error=err.name, message=err.description), err.code

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
