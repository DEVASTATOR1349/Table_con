-- Тополь SQL Schema — дубляж данных Google Sheets

CREATE TABLE IF NOT EXISTS clients (
    id SERIAL PRIMARY KEY,
    sheet_id_ext VARCHAR(50),
    project VARCHAR(255),
    name VARCHAR(255),
    category VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scenarios (
    id SERIAL PRIMARY KEY,
    sheet_row_id VARCHAR(50),
    client_id INT REFERENCES clients(id),
    project VARCHAR(255),
    date DATE,
    link VARCHAR(1000),
    category VARCHAR(255),
    scenario_type VARCHAR(100),
    visual_format VARCHAR(255),
    analysis TEXT,
    views VARCHAR(100),
    transcript TEXT,
    timeline TEXT,
    why_viral TEXT,
    borrow TEXT,
    improve TEXT,
    scenario_text TEXT,
    montage_tz TEXT,
    hook TEXT,
    retention VARCHAR(50),
    cta TEXT,
    scenarist VARCHAR(255),
    speaker VARCHAR(255),
    cover_text VARCHAR(500),
    comment TEXT,
    status VARCHAR(50) DEFAULT 'new',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS montage_tasks (
    id SERIAL PRIMARY KEY,
    sheet_row_id VARCHAR(50),
    scenario_id INT REFERENCES scenarios(id),
    project VARCHAR(255),
    scenarist VARCHAR(255),
    cover_text VARCHAR(500),
    scenario_text TEXT,
    deadline DATE,
    source_link VARCHAR(1000),
    client_style TEXT,
    montage_tz TEXT,
    montage_tz_extra TEXT,
    status_scenarist VARCHAR(50),
    comment_scenarist TEXT,
    source_approved VARCHAR(50),
    comment_source TEXT,
    montager VARCHAR(255),
    price VARCHAR(50),
    ready_link VARCHAR(1000),
    status_montager VARCHAR(50),
    comment_montager TEXT,
    approved VARCHAR(50),
    comment_manager TEXT,
    ready_date DATE,
    client_approved VARCHAR(50),
    client_comment TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sync_log (
    id SERIAL PRIMARY KEY,
    step_id INT,
    action VARCHAR(100),
    source_table VARCHAR(255),
    target_table VARCHAR(255),
    row_id VARCHAR(50),
    status VARCHAR(20),
    details TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scenarios_status ON scenarios(status);
CREATE INDEX IF NOT EXISTS idx_montage_status ON montage_tasks(status_montager);
CREATE INDEX IF NOT EXISTS idx_sync_log_time ON sync_log(created_at);
CREATE INDEX IF NOT EXISTS idx_clients_project ON clients(project);
