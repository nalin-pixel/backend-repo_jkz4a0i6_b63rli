"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Project -> "project" collection
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Literal

class User(BaseModel):
    """
    Users collection schema
    Collection name: "user"
    """
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address (unique)")
    plan: Literal["free", "pro"] = Field("free", description="Subscription plan")
    api_key: Optional[str] = Field(None, description="API key for authentication")

class Project(BaseModel):
    """
    Projects collection schema
    Collection name: "project"
    """
    owner_email: EmailStr = Field(..., description="Owner email (references user)")
    name: str = Field(..., description="Project name")
    description: Optional[str] = Field(None, description="Project description")
    status: Literal["active", "archived"] = Field("active", description="Project status")
