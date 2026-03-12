"""
Deployment Management Endpoints
Handles deployment tracking, version management, and rollback functionality
"""

import uuid
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel
import logging

from src.version import get_version_info
from src.database import get_connection

logger = logging.getLogger(__name__)
router = APIRouter()

# ============================================
# Pydantic Models
# ============================================

class DeploymentComponent(BaseModel):
    component_name: str
    component_version: str
    component_sha: Optional[str] = None
    image_tag: Optional[str] = None
    health_check_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = {}

class DeploymentRequest(BaseModel):
    deployment_id: str
    version: Optional[str] = None
    description: Optional[str] = None
    deployed_by: Optional[str] = "system"
    environment: Optional[str] = "development"
    components: List[DeploymentComponent]

class DeploymentStatus(BaseModel):
    deployment_id: str
    status: str
    component_status: Optional[Dict[str, str]] = {}

class RollbackRequest(BaseModel):
    original_deployment_id: str
    rollback_reason: str
    rollback_type: str = "manual"
    triggered_by: Optional[str] = "system"
    rollback_notes: Optional[str] = None

# ============================================
# Helper Functions
# ============================================

async def register_deployment_in_db(deployment_data: DeploymentRequest) -> Dict[str, Any]:
    """Register a new deployment in the database"""
    try:
        async with get_connection() as conn:
            # Get current version info if not provided
            version_info = get_version_info()
            version = deployment_data.version or version_info.get("version", "unknown")
            
            # Insert deployment record
            deployment_query = """
                INSERT INTO deployments (
                    deployment_id, version, git_sha, git_branch, build_time, 
                    environment, status, description, deployed_by
                ) VALUES ($1, $2, $3, $4, $5, $6, 'deploying', $7, $8)
                RETURNING id, started_at
            """
            
            deployment_row = await conn.fetchrow(
                deployment_query,
                deployment_data.deployment_id,
                version,
                version_info.get("git_sha"),
                version_info.get("git_branch"),
                version_info.get("build_time"),
                deployment_data.environment,
                deployment_data.description,
                deployment_data.deployed_by
            )
            
            deployment_id = deployment_row["id"]
            started_at = deployment_row["started_at"]
            
            # Insert component records
            component_queries = []
            for component in deployment_data.components:
                component_query = """
                    INSERT INTO deployment_components (
                        deployment_id, component_name, component_version, 
                        component_sha, image_tag, health_check_url, 
                        status, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7)
                    RETURNING id
                """
                component_queries.append((
                    component_query,
                    deployment_id,
                    component.component_name,
                    component.component_version,
                    component.component_sha,
                    component.image_tag,
                    component.health_check_url,
                    component.metadata
                ))
            
            # Execute all component inserts
            component_ids = []
            for query, *params in component_queries:
                component_row = await conn.fetchrow(query, *params)
                component_ids.append(component_row["id"])
            
            return {
                "deployment_id": deployment_id,
                "deployment_key": deployment_data.deployment_id,
                "started_at": started_at,
                "component_count": len(component_ids),
                "status": "deploying"
            }
            
    except Exception as e:
        logger.error(f"Failed to register deployment: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to register deployment: {str(e)}")

async def update_deployment_status(deployment_id: str, status: str, component_updates: Optional[Dict[str, str]] = None) -> bool:
    """Update deployment and component status"""
    try:
        async with get_connection() as conn:
            # Update deployment status
            update_query = """
                UPDATE deployments 
                SET status = $1, updated_at = NOW()
                WHERE deployment_id = $2
            """
            await conn.execute(update_query, status, deployment_id)
            
            # Update component statuses if provided
            if component_updates:
                for component_name, component_status in component_updates.items():
                    component_update_query = """
                        UPDATE deployment_components 
                        SET status = $1, completed_at = NOW(), updated_at = NOW()
                        WHERE deployment_id = (
                            SELECT id FROM deployments WHERE deployment_id = $2
                        ) AND component_name = $3
                    """
                    await conn.execute(component_update_query, component_status, deployment_id, component_name)
            
            return True
            
    except Exception as e:
        logger.error(f"Failed to update deployment status: {str(e)}")
        return False

async def get_deployment_info(deployment_id: str) -> Optional[Dict[str, Any]]:
    """Get detailed deployment information"""
    try:
        async with get_connection() as conn:
            # Get deployment info
            deployment_query = """
                SELECT d.*, 
                       COUNT(dc.id) as component_count,
                       COUNT(CASE WHEN dc.status = 'success' THEN 1 END) as success_components
                FROM deployments d
                LEFT JOIN deployment_components dc ON d.id = dc.deployment_id
                WHERE d.deployment_id = $1
                GROUP BY d.id
            """
            deployment = await conn.fetchrow(deployment_query, deployment_id)
            
            if not deployment:
                return None
            
            # Get component details
            components_query = """
                SELECT component_name, component_version, component_sha, 
                       image_tag, status, health_check_url, started_at, 
                       completed_at, metadata
                FROM deployment_components
                WHERE deployment_id = (SELECT id FROM deployments WHERE deployment_id = $1)
                ORDER BY component_name
            """
            components = await conn.fetch(components_query, deployment_id)
            
            return {
                "deployment_id": deployment["deployment_id"],
                "version": deployment["version"],
                "git_sha": deployment["git_sha"],
                "git_branch": deployment["git_branch"],
                "build_time": deployment["build_time"],
                "environment": deployment["environment"],
                "status": deployment["status"],
                "description": deployment["description"],
                "deployed_by": deployment["deployed_by"],
                "started_at": deployment["started_at"],
                "completed_at": deployment["completed_at"],
                "component_count": deployment["component_count"],
                "success_components": deployment["success_components"],
                "components": [dict(comp) for comp in components]
            }
            
    except Exception as e:
        logger.error(f"Failed to get deployment info: {str(e)}")
        return None

# ============================================
# API Endpoints
# ============================================

@router.post("/deployments/register", response_model=Dict[str, Any])
async def register_deployment(deployment: DeploymentRequest, background_tasks: BackgroundTasks):
    """Register a new deployment"""
    logger.info(f"Registering deployment: {deployment.deployment_id}")
    
    # Register deployment in database
    result = await register_deployment_in_db(deployment)
    
    # Start background task to monitor deployment
    background_tasks.add_task(monitor_deployment_progress, deployment.deployment_id)
    
    return {
        "success": True,
        "deployment_id": deployment.deployment_id,
        "message": "Deployment registered successfully",
        "details": result
    }

@router.post("/deployments/register-simple")
async def register_current_version():
    """Simple endpoint to register current version on startup"""
    try:
        version_info = get_version_info()
        deployment_id = f"v{version_info.get('version', 'unknown')}-{version_info.get('git_sha', 'unknown')[:8]}"
        
        deployment_data = DeploymentRequest(
            deployment_id=deployment_id,
            version=version_info.get('version'),
            description=f"Auto-registered deployment for version {version_info.get('version')}",
            deployed_by="system",
            environment=version_info.get('environment', 'development'),
            components=[
                DeploymentComponent(
                    component_name="backend",
                    component_version=version_info.get('version'),
                    component_sha=version_info.get('git_sha'),
                    metadata={
                        "build_time": version_info.get('build_time'),
                        "git_branch": version_info.get('git_branch')
                    }
                )
            ]
        )
        
        result = await register_deployment_in_db(deployment_data)
        
        # Auto-mark as successful since we're running
        await update_deployment_status(deployment_id, "success", {"backend": "success"})
        
        return {
            "success": True,
            "deployment_id": deployment_id,
            "message": "Current version registered successfully",
            "version_info": version_info
        }
        
    except Exception as e:
        logger.error(f"Failed to register current version: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "version_info": get_version_info()
        }

@router.get("/deployments/current")
async def get_current_deployment():
    """Get current successful deployment information"""
    try:
        async with get_connection() as conn:
            query = """
                SELECT DISTINCT ON (component_name)
                    dc.component_name,
                    dc.component_version,
                    dc.component_sha,
                    dc.image_tag,
                    dc.status as component_status,
                    d.deployment_id,
                    d.version,
                    d.git_sha,
                    d.git_branch,
                    d.build_time,
                    d.environment,
                    d.status as deployment_status,
                    d.completed_at as deployed_at
                FROM deployment_components dc
                JOIN deployments d ON dc.deployment_id = d.id
                WHERE d.status = 'success'
                ORDER BY component_name, d.completed_at DESC
            """
            current_components = await conn.fetch(query)
            
            if not current_components:
                # Return current version info from code if no deployments tracked
                version_info = get_version_info()
                return {
                    "deployment_id": "development",
                    "version": version_info.get("version"),
                    "git_sha": version_info.get("git_sha"),
                    "git_branch": version_info.get("git_branch"),
                    "build_time": version_info.get("build_time"),
                    "environment": version_info.get("environment"),
                    "components": [
                        {
                            "component_name": "backend",
                            "component_version": version_info.get("version"),
                            "component_sha": version_info.get("git_sha"),
                            "status": "running"
                        }
                    ]
                }
            
            # Group by deployment
            deployment_info = None
            components = []
            
            for comp in current_components:
                if not deployment_info:
                    deployment_info = {
                        "deployment_id": comp["deployment_id"],
                        "version": comp["version"],
                        "git_sha": comp["git_sha"],
                        "git_branch": comp["git_branch"],
                        "build_time": comp["build_time"],
                        "environment": comp["environment"],
                        "deployment_status": comp["deployment_status"],
                        "deployed_at": comp["deployed_at"]
                    }
                
                components.append({
                    "component_name": comp["component_name"],
                    "component_version": comp["component_version"],
                    "component_sha": comp["component_sha"],
                    "image_tag": comp["image_tag"],
                    "status": comp["component_status"]
                })
            
            deployment_info["components"] = components
            return deployment_info
            
    except Exception as e:
        logger.error(f"Failed to get current deployment: {str(e)}")
        # Fallback to version info
        version_info = get_version_info()
        return {
            "deployment_id": "development",
            "version": version_info.get("version"),
            "git_sha": version_info.get("git_sha"),
            "git_branch": version_info.get("git_branch"),
            "build_time": version_info.get("build_time"),
            "environment": version_info.get("environment"),
            "components": [
                {
                    "component_name": "backend",
                    "component_version": version_info.get("version"),
                    "component_sha": version_info.get("git_sha"),
                    "status": "running"
                }
            ]
        }

@router.get("/deployments")
async def get_deployments(
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    environment: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None)
):
    """Get deployment history with optional filtering"""
    try:
        async with get_connection() as conn:
            # Build base query
            base_query = """
                SELECT d.deployment_id, d.version, d.git_sha, d.git_branch,
                       d.environment, d.status, d.description, d.deployed_by,
                       d.started_at, d.completed_at,
                       COUNT(dc.id) as component_count,
                       COUNT(CASE WHEN dc.status = 'success' THEN 1 END) as success_components
                FROM deployments d
                LEFT JOIN deployment_components dc ON d.id = dc.deployment_id
            """
            
            # Add filters
            conditions = []
            params = []
            param_count = 0
            
            if environment:
                param_count += 1
                conditions.append(f"d.environment = ${param_count}")
                params.append(environment)
            
            if status:
                param_count += 1
                conditions.append(f"d.status = ${param_count}")
                params.append(status)
            
            if conditions:
                base_query += " WHERE " + " AND ".join(conditions)
            
            # Add grouping and ordering
            base_query += """
                GROUP BY d.id, d.deployment_id, d.version, d.git_sha, d.git_branch,
                         d.environment, d.status, d.description, d.deployed_by,
                         d.started_at, d.completed_at
                ORDER BY d.started_at DESC
                LIMIT $%d OFFSET $%d
            """ % (param_count + 1, param_count + 2)
            
            params.extend([limit, offset])
            
            deployments = await conn.fetch(base_query, *params)
            
            # Calculate overall status for each deployment
            result = []
            for deployment in deployments:
                overall_status = "unknown"
                if deployment["status"] == "success":
                    if deployment["component_count"] == deployment["success_components"]:
                        overall_status = "fully_successful"
                    else:
                        overall_status = "partial"
                elif deployment["status"] == "failed":
                    overall_status = "failed"
                elif deployment["status"] == "rolled_back":
                    overall_status = "rolled_back"
                else:
                    overall_status = deployment["status"]
                
                result.append({
                    "deployment_id": deployment["deployment_id"],
                    "version": deployment["version"],
                    "git_sha": deployment["git_sha"],
                    "git_branch": deployment["git_branch"],
                    "environment": deployment["environment"],
                    "status": deployment["status"],
                    "overall_status": overall_status,
                    "description": deployment["description"],
                    "deployed_by": deployment["deployed_by"],
                    "started_at": deployment["started_at"],
                    "completed_at": deployment["completed_at"],
                    "component_count": deployment["component_count"],
                    "success_components": deployment["success_components"]
                })
            
            return {
                "deployments": result,
                "total": len(result),
                "limit": limit,
                "offset": offset
            }
            
    except Exception as e:
        logger.error(f"Failed to get deployments: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get deployments: {str(e)}")

@router.get("/deployments/{deployment_id}")
async def get_deployment_details(deployment_id: str):
    """Get detailed information about a specific deployment"""
    deployment_info = await get_deployment_info(deployment_id)
    
    if not deployment_info:
        raise HTTPException(status_code=404, detail=f"Deployment {deployment_id} not found")
    
    return deployment_info

@router.post("/deployments/{deployment_id}/status")
async def update_deployment_status_endpoint(
    deployment_id: str, 
    status_update: DeploymentStatus,
    background_tasks: BackgroundTasks
):
    """Update deployment status (for CI/CD integration)"""
    success = await update_deployment_status(deployment_id, status_update.status, status_update.component_status)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update deployment status")
    
    # If deployment is complete, mark as success/failed
    if status_update.status in ["success", "failed"]:
        background_tasks.add_task(finalize_deployment, deployment_id, status_update.status)
    
    return {
        "success": True,
        "message": f"Deployment status updated to {status_update.status}"
    }

@router.post("/deployments/{deployment_id}/rollback")
async def initiate_rollback(deployment_id: str, rollback_request: RollbackRequest):
    """Initiate a rollback to a previous deployment"""
    try:
        async with get_connection() as conn:
            # Get current deployment info
            current_deployment = await get_deployment_info(deployment_id)
            if not current_deployment:
                raise HTTPException(status_code=404, detail=f"Deployment {deployment_id} not found")
            
            # Find previous successful deployment
            previous_query = """
                SELECT deployment_id, version, git_sha, git_branch
                FROM deployments
                WHERE status = 'success' 
                AND started_at < (SELECT started_at FROM deployments WHERE deployment_id = $1)
                ORDER BY started_at DESC
                LIMIT 1
            """
            previous = await conn.fetchrow(previous_query, deployment_id)
            
            if not previous:
                raise HTTPException(status_code=400, detail="No previous successful deployment found for rollback")
            
            # Create rollback deployment record
            rollback_deployment_id = f"rollback-{deployment_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            # Insert rollback record
            rollback_query = """
                INSERT INTO deployment_rollbacks (
                    original_deployment_id, rollback_deployment_id, rollback_reason,
                    rollback_type, triggered_by, rollback_notes
                ) VALUES (
                    (SELECT id FROM deployments WHERE deployment_id = $1),
                    (SELECT id FROM deployments WHERE deployment_id = $2),
                    $3, $4, $5, $6
                )
                RETURNING id
            """
            
            await conn.execute(
                rollback_query,
                deployment_id,
                rollback_deployment_id,
                rollback_request.rollback_reason,
                rollback_request.rollback_type,
                rollback_request.triggered_by,
                rollback_request.rollback_notes
            )
            
            # Update current deployment status
            await update_deployment_status(deployment_id, "rolled_back")
            
            return {
                "success": True,
                "message": "Rollback initiated successfully",
                "rollback_deployment_id": rollback_deployment_id,
                "rolling_back_to": {
                    "deployment_id": previous["deployment_id"],
                    "version": previous["version"],
                    "git_sha": previous["git_sha"]
                }
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to initiate rollback: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to initiate rollback: {str(e)}")

# ============================================
# Background Tasks
# ============================================

async def monitor_deployment_progress(deployment_id: str):
    """Background task to monitor deployment progress"""
    logger.info(f"Starting deployment monitoring for {deployment_id}")
    
    # This would typically involve checking component health endpoints
    # For now, we'll simulate a successful deployment after some time
    await asyncio.sleep(30)  # Simulate deployment time
    
    success = await update_deployment_status(deployment_id, "success", {
        "backend": "success",
        "frontend": "success"
    })
    
    if success:
        logger.info(f"Deployment {deployment_id} completed successfully")
    else:
        logger.error(f"Failed to update deployment status for {deployment_id}")

async def finalize_deployment(deployment_id: str, final_status: str):
    """Finalize deployment completion"""
    try:
        async with get_connection() as conn:
            # Update completion time
            query = """
                UPDATE deployments 
                SET completed_at = NOW(), updated_at = NOW()
                WHERE deployment_id = $1
            """
            await conn.execute(query, deployment_id)
            
            logger.info(f"Deployment {deployment_id} finalized with status: {final_status}")
            
    except Exception as e:
        logger.error(f"Failed to finalize deployment {deployment_id}: {str(e)}")
