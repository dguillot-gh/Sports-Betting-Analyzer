-- ============================================
-- Deployment Tracking System
-- Adds tables to track deployments, versions, and rollbacks
-- ============================================

-- ============================================
-- DEPLOYMENTS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS deployments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deployment_id VARCHAR(100) UNIQUE NOT NULL,  -- e.g., "v1.2.3-abc123"
    version VARCHAR(50) NOT NULL,
    git_sha VARCHAR(40),
    git_branch VARCHAR(100),
    build_time TIMESTAMP,
    environment VARCHAR(50) DEFAULT 'development',
    status VARCHAR(20) DEFAULT 'pending',  -- pending, deploying, success, failed, rolled_back
    description TEXT,
    deployed_by VARCHAR(100),
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- DEPLOYMENT COMPONENTS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS deployment_components (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    deployment_id UUID REFERENCES deployments(id) ON DELETE CASCADE,
    component_name VARCHAR(50) NOT NULL,  -- backend, frontend, database, mobile
    component_version VARCHAR(50) NOT NULL,
    component_sha VARCHAR(40),
    image_tag VARCHAR(200),  -- Docker image tag
    status VARCHAR(20) DEFAULT 'pending',
    health_check_url VARCHAR(500),
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    rollback_info JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(deployment_id, component_name)
);

-- ============================================
-- DEPLOYMENT ROLLBACKS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS deployment_rollbacks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    original_deployment_id UUID REFERENCES deployments(id),
    rollback_deployment_id UUID REFERENCES deployments(id),
    rollback_reason TEXT NOT NULL,
    rollback_type VARCHAR(50) DEFAULT 'manual',  -- manual, automatic, health_check
    triggered_by VARCHAR(100),
    rollback_started_at TIMESTAMP DEFAULT NOW(),
    rollback_completed_at TIMESTAMP,
    rollback_success BOOLEAN DEFAULT FALSE,
    rollback_notes TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================
-- INDEXES FOR PERFORMANCE
-- ============================================

-- Deployments indexes
CREATE INDEX IF NOT EXISTS idx_deployments_status ON deployments(status);
CREATE INDEX IF NOT EXISTS idx_deployments_environment ON deployments(environment);
CREATE INDEX IF NOT EXISTS idx_deployments_created_at ON deployments(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_deployments_version ON deployments(version);

-- Deployment components indexes
CREATE INDEX IF NOT EXISTS idx_deployment_components_deployment_id ON deployment_components(deployment_id);
CREATE INDEX IF NOT EXISTS idx_deployment_components_status ON deployment_components(status);
CREATE INDEX IF NOT EXISTS idx_deployment_components_name ON deployment_components(component_name);

-- Rollback indexes
CREATE INDEX IF NOT EXISTS idx_rollbacks_original_deployment ON deployment_rollbacks(original_deployment_id);
CREATE INDEX IF NOT EXISTS idx_rollbacks_rollback_deployment ON deployment_rollbacks(rollback_deployment_id);

-- ============================================
-- VIEWS FOR COMMON QUERIES
-- ============================================

-- Current deployment view
CREATE OR REPLACE VIEW current_deployment AS
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
ORDER BY component_name, d.completed_at DESC;

-- Deployment history view
CREATE OR REPLACE VIEW deployment_history AS
SELECT 
    d.deployment_id,
    d.version,
    d.git_sha,
    d.git_branch,
    d.environment,
    d.status,
    d.description,
    d.deployed_by,
    d.started_at,
    d.completed_at,
    COUNT(dc.id) as component_count,
    COUNT(CASE WHEN dc.status = 'success' THEN 1 END) as success_components,
    CASE 
        WHEN d.status = 'success' AND COUNT(dc.id) = COUNT(CASE WHEN dc.status = 'success' THEN 1 END) 
        THEN 'fully_successful'
        WHEN d.status = 'failed' THEN 'failed'
        WHEN d.status = 'rolled_back' THEN 'rolled_back'
        ELSE 'partial'
    END as overall_status
FROM deployments d
LEFT JOIN deployment_components dc ON d.id = dc.deployment_id
GROUP BY d.id, d.deployment_id, d.version, d.git_sha, d.git_branch, d.environment, 
         d.status, d.description, d.deployed_by, d.started_at, d.completed_at
ORDER BY d.started_at DESC;

-- ============================================
-- FUNCTIONS FOR AUTOMATIC UPDATES
-- ============================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
CREATE TRIGGER update_deployments_updated_at BEFORE UPDATE ON deployments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_deployment_components_updated_at BEFORE UPDATE ON deployment_components
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- SAMPLE DATA (Optional - for development)
-- ============================================

-- Insert a sample deployment for testing
INSERT INTO deployments (
    deployment_id, version, git_sha, git_branch, build_time, 
    environment, status, description, deployed_by, completed_at
) VALUES (
    'v1.0.0-initial',
    '1.0.0',
    'abc123def456',
    'main',
    NOW() - INTERVAL '1 day',
    'development',
    'success',
    'Initial deployment with version tracking',
    'system',
    NOW() - INTERVAL '1 day'
) ON CONFLICT (deployment_id) DO NOTHING;

-- Insert sample components
INSERT INTO deployment_components (
    deployment_id, component_name, component_version, component_sha, 
    image_tag, status, completed_at
) VALUES 
    ((SELECT id FROM deployments WHERE deployment_id = 'v1.0.0-initial'), 
     'backend', '1.0.0', 'abc123def456', 'ghcr.io/dguillot-gh/sports-ml-service:latest', 
     'success', NOW() - INTERVAL '1 day'),
    ((SELECT id FROM deployments WHERE deployment_id = 'v1.0.0-initial'), 
     'frontend', '1.0.0', 'abc123def456', 'ghcr.io/dguillot-gh/sports-betting-analyzer:latest', 
     'success', NOW() - INTERVAL '1 day')
ON CONFLICT (deployment_id, component_name) DO NOTHING;
