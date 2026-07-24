# Bill Categories API Documentation

This document covers the bill categories endpoint under the bill categories module.

Base URL:
- `/api/v1/bill-categories/`

## Overview

This endpoint returns the active bill categories available for the authenticated user.

All bill category endpoints require authentication via a valid access token.

---

## 1. List Bill Categories

### Endpoint
- `GET /api/v1/bill-categories/`

### Purpose
Retrieve all active bill categories.

### Authentication
- Requires `Authorization: Bearer <access_token>`

### Success Response
```json
{
  "success": true,
  "message": "Success",
  "data": [
    {
      "id": "1f2e3d4c-5b6a-4c7d-8e9f-0123456789ab",
      "name": "Utilities",
      "icon": "https://example.com/icons/utilities.png",
      "color": "#FF5733",
      "displayOrder": 1
    },
    {
      "id": "2a3b4c5d-6e7f-8a9b-0c1d-2e3f4a5b6c7d",
      "name": "Internet",
      "icon": "https://example.com/icons/internet.png",
      "color": "#00AEEF",
      "displayOrder": 2
    }
  ]
}
```

### Response Fields
- `id`: UUID of the bill category
- `name`: Category name
- `icon`: Category icon URL
- `color`: Category color code
- `displayOrder`: Display order of the category

### Example Request
```bash
curl -X GET "http://127.0.0.1:8000/api/v1/bill-categories/" \
  -H "Authorization: Bearer <access_token>"
```

### Notes
- This endpoint returns only active bill categories.
- The response field `displayOrder` maps to the internal `display_order` field.

---

## Error Responses

### 401 Unauthorized
```json
{
  "success": false,
  "message": "Authentication credentials were not provided."
}
```