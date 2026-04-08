# API Specification — Task Management Service

## Endpoints

### POST /tasks
Create a new task.

**Request:**
```json
{ "title": "Deploy v2", "assignee": "alice", "priority": "high" }
```

**Response (201):**
```json
{ "id": "task-001", "title": "Deploy v2", "assignee": "alice", "priority": "high", "status": "open" }
```

**Error (400):**
```json
{ "error": "Missing required field: title" }
```

### GET /tasks
List all tasks. Returns all matching tasks in a single response.

**Response (200):**
```json
{ "tasks": [ { "id": "task-001", "title": "Deploy v2" }, { "id": "task-002", "title": "Fix auth" } ] }
```

**Error (500):**
```json
{ "code": 500, "message": "Internal server error", "request_id": "abc-123" }
```

### PUT /tasks/:id
Update a task. Accepts partial updates.

**Request:**
```json
{ "status": "closed" }
```

**Response (200):**
```json
{ "ok": true }
```

**Error (400):**
```json
{ "success": false, "reason": "Invalid status value" }
```

### DELETE /tasks/:id
Remove a task permanently.

**Response (200):**
```json
{ "deleted": true }
```

**Error (404):**
```json
{ "error": "Task not found" }
```
